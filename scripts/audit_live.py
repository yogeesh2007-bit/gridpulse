"""Black-box audit of the deployed site (Vercel frontend + Render backend). Read-mostly; creates a few throwaway accounts.

    python scripts/audit_live.py https://gridpulse-topaz.vercel.app https://gridpulse-api-yjd1.onrender.com
"""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets
from playwright.sync_api import sync_playwright

V = (sys.argv[1] if len(sys.argv) > 1 else "https://gridpulse-topaz.vercel.app").rstrip("/")
R = (sys.argv[2] if len(sys.argv) > 2 else "https://gridpulse-api-yjd1.onrender.com").rstrip("/")
SHOTS = Path(__file__).resolve().parents[1] / "e2e-shots"
SHOTS.mkdir(exist_ok=True)
F = []


def note(sev, msg):
    F.append((sev, msg))
    print(f"  [{sev}] {msg}")


print("== 1. headers and exposure")
h = httpx.Client(timeout=90, follow_redirects=False)
r = h.get(V + "/")
hd = {k.lower(): v for k, v in r.headers.items()}
print("  vercel:", {k: (hd.get(k) or "-")[:40] for k in ("strict-transport-security", "content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy")})
for k in ("content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy"):
    if k not in hd:
        note("SEC-LOW", f"Vercel site sends no {k} header")
t0 = time.time()
rr = h.get(R + "/health")
print(f"  render /health: {rr.status_code} in {time.time() - t0:.1f}s")
rh = {k.lower(): v for k, v in rr.headers.items()}
for k in ("x-content-type-options", "x-frame-options", "strict-transport-security"):
    if k not in rh:
        note("SEC-LOW", f"Render API sends no {k} header")
for path in ("/docs", "/openapi.json", "/redoc"):
    if h.get(R + path).status_code == 200:
        note("SEC-LOW", f"API documentation {path} is publicly readable on the backend host")
for path, m in (("/stations", "get"), ("/seed", "post"), ("/dashboard/state", "get"), ("/devices", "get"), ("/control/state", "get")):
    s = getattr(h, m)(R + path).status_code
    if s != 404:
        note("SEC-HIGH", f"legacy open endpoint {path} is reachable ({s})")
s = h.post(R + "/telemetry/update", json={"device_id": "x", "voltage": 1, "current": 1, "power": 1}).status_code
print("  device telemetry without key ->", s)
if s not in (401, 403):
    note("SEC-HIGH", f"device telemetry accepts unauthenticated writes ({s})")

print("== 2. auth and authorization (through the Vercel proxy)")
c = httpx.Client(base_url=V, timeout=90)
email = f"audit-{uuid.uuid4().hex[:6]}@example.com"
r = c.post("/api/auth/signup", json={"name": "Audit", "email": email, "password": "audit-pass1"})
sc = r.headers.get("set-cookie", "").lower()
print("  signup", r.status_code, "| cookie flags present:", [f for f in ("httponly", "secure", "samesite=lax", "path=/api/auth") if f in sc])
for f in ("httponly", "secure"):
    if f not in sc:
        note("SEC-HIGH", f"refresh cookie is missing {f}")
tok = r.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
for path, m, want in (("/api/operator/state", "get", 403), ("/api/operator/seed", "post", 403), ("/api/driver/stations", "get", 200), ("/api/auth/me", "get", 200)):
    s = getattr(c, m)(path, headers=H).status_code
    if s != want:
        note("SEC-HIGH", f"{m.upper()} {path} as a driver returned {s}, expected {want}")
for path in ("/api/operator/state", "/api/driver/stations", "/api/geo/reverse?lat=1&lon=1"):
    if c.get(path).status_code != 401:
        note("SEC-HIGH", f"{path} is reachable without a token")
body = {"name": "X", "email": f"op-{uuid.uuid4().hex[:5]}@example.com", "password": "audit-pass1", "role": "operator"}
print("  operator sign-up, wrong code ->", c.post("/api/auth/signup", json={**body, "operator_code": "wrong"}).status_code,
      "| no code ->", c.post("/api/auth/signup", json={**body, "email": f"op-{uuid.uuid4().hex[:5]}@example.com"}).status_code)
if c.post("/api/auth/signup", json={**body, "email": f"op-{uuid.uuid4().hex[:5]}@example.com", "operator_code": "operator-demo"}).status_code == 201:
    note("SEC-HIGH", "the development operator code 'operator-demo' works in production")
for b, label in (({"lat": 13, "lng": 80, "soc": -5, "target_soc": 80, "deadline": 90}, "negative charge"),
                 ({"lat": 13, "lng": 80, "soc": 50, "target_soc": 40, "deadline": 90}, "target below current"),
                 ({"lat": "abc", "lng": 80, "soc": 5, "target_soc": 80, "deadline": 90}, "non-numeric latitude")):
    if c.post("/api/driver/recommend", json=b, headers=H).status_code != 422:
        note("BUG", f"input validation: {label} was not rejected with 422")

print("== 3. recommendation, geocoding, AI, WebSocket")
t0 = time.time()
rec = c.post("/api/driver/recommend", json={"lat": 13.0067, "lng": 80.0037, "soc": 12, "target_soc": 80, "deadline": 90}, headers=H).json()
print(f"  recommend in {time.time() - t0:.1f}s | chosen: {rec['chosen_station']['name']} | routing: {rec['routing']['sources']} confidence={rec['routing']['confidence']}")
g = c.get("/api/geo/reverse?lat=13.0067&lon=80.0037", headers=H).json()
print("  geocode:", g["source"], "|", g["short_name"])
if g["source"] == "fallback":
    note("INFO", "reverse geocoding fell back to raw coordinates (Nominatim unreachable/blocked from the backend host)")
t0 = time.time()
ex = c.post("/api/explain", json={"request_id": rec["request_id"]}, headers=H).json()
print(f"  explain: source={ex['source']} model={ex.get('model')} in {time.time() - t0:.1f}s")
if ex["source"] == "rules":
    note("INFO", f"the AI rewrite fell back to rules on the live site: {ex.get('fallback_reason')}")


async def ws(token):
    try:
        async with websockets.connect(R.replace("https", "wss") + "/api/ws?token=" + token) as w:
            a = json.loads(await asyncio.wait_for(w.recv(), 20))["type"]
            b = json.loads(await asyncio.wait_for(w.recv(), 20))["type"]
            return a, b
    except Exception as e:
        return ("closed", str(e)[:60])


print("  websocket, valid token:", asyncio.run(ws(tok)), "| bad token:", asyncio.run(ws("bad")))

print("== 4. real browser, phone-sized")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, geolocation={"latitude": 13.0067, "longitude": 80.0037}, permissions=["geolocation"])
    p = ctx.new_page()
    bad = []
    p.on("response", lambda x: bad.append((x.status, x.url.split("//")[-1][:60])) if x.status >= 400 and "refresh" not in x.url else None)
    t0 = time.time()
    p.goto(V, wait_until="load")
    print(f"  landing loaded in {time.time() - t0:.1f}s | title: {p.title()}")
    if p.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        note("BUG", "landing page scrolls sideways on a 390px phone")
    p.goto(V + "/signup")
    p.get_by_label("Name").fill("Audit UI")
    p.get_by_label("Email").fill(f"ui-{uuid.uuid4().hex[:6]}@example.com")
    p.get_by_label("Password").fill("audit-pass1")
    p.get_by_role("button", name="Create account").click()
    p.wait_for_url("**/app/driver**", timeout=60000)
    p.get_by_role("button", name="Use my location").click()
    p.wait_for_selector("[data-testid=coords]", timeout=20000)
    p.get_by_label("Current charge (number)").fill("12")
    p.get_by_label("Must be done within (minutes)").fill("90")
    p.get_by_role("button", name="Find best charger").click()
    p.wait_for_selector("[data-testid=station-card]", timeout=60000)
    print("  station cards:", p.get_by_test_id("station-card").count(), "| best:", p.get_by_test_id("station-card").first.get_attribute("data-station"))
    if p.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        note("BUG", "driver page scrolls sideways on a 390px phone")
    p.get_by_role("button", name="Reserve at B").click()
    p.wait_for_selector("[data-testid=reservation-card]", timeout=30000)
    p.wait_for_timeout(5000)
    print("  reservation created | live pill:", p.locator("[role=status]").first.inner_text().replace("\n", " "))
    p.screenshot(path=str(SHOTS / "live-driver-mobile.png"), full_page=True)
    p.reload()
    p.wait_for_selector("[data-testid=reservation-card]", timeout=30000)
    print("  reservation restored after reload")
    p.goto(V + "/app/operator")
    p.wait_for_url("**/app/driver**", timeout=20000)
    print("  driver kept out of /app/operator")
    p.goto(V + "/nope")
    print("  404 page shown:", p.get_by_text("does not exist").is_visible())
    print("  other 4xx/5xx responses:", bad or "none")
    b.close()

print(f"\nFINDINGS ({len(F)})")
for sev, msg in F:
    print(f" - [{sev}] {msg}")
