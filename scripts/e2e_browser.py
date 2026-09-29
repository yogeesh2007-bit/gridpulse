"""Real-browser end-to-end test of the single-URL web app (Playwright + the installed Chrome).

Needs the backend running with the built frontend on http://localhost:8000 (development mode: demo users enabled).
    pip install playwright
    python scripts/e2e_browser.py            # add --headed to watch; screenshots go to ./e2e-shots/
WARNING: it resets the demo data via the operator UI/API.
"""
import re
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:8000"
SHOTS = Path(__file__).resolve().parents[1] / "e2e-shots"
SHOTS.mkdir(exist_ok=True)
HEADED = "--headed" in sys.argv
ok = True


def check(label, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label, extra)


def sign_in(page, email, password):
    page.goto(f"{BASE}/signin")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=not HEADED)

    # ---------------------------------------------------------------- landing + sign up (driver, phone-sized)
    driver_ctx = browser.new_context(viewport={"width": 390, "height": 844}, geolocation={"latitude": 13.0067, "longitude": 80.0037},
                                     permissions=["geolocation"])
    d = driver_ctx.new_page()
    d.goto(BASE)
    check("landing page renders", d.get_by_role("heading", name=re.compile("Charge smarter")).is_visible())
    d.screenshot(path=str(SHOTS / "01-landing-mobile.png"))

    # protected routes redirect anonymous users to sign-in
    d.goto(f"{BASE}/app/driver")
    d.wait_for_url("**/signin")
    check("anonymous /app/driver -> /signin", "/signin" in d.url)

    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    d.goto(f"{BASE}/signup")
    d.get_by_label("Name").fill("Browser Driver")
    d.get_by_label("Email").fill(email)
    d.get_by_label("Password").fill("browser-pass1")
    d.get_by_role("button", name="Create account").click()
    d.wait_for_url("**/app/driver**")
    check("sign up lands on the driver area", "/app/driver" in d.url)

    # role protection: a driver cannot open the operator area
    d.goto(f"{BASE}/app/operator")
    d.wait_for_url("**/app/driver**")
    check("driver redirected away from /app/operator", "/app/driver" in d.url)

    # session survives a reload (httpOnly refresh cookie)
    d.reload()
    expect(d.get_by_role("heading", name="Your location")).to_be_visible()
    check("session restored after reload", True)

    # mobile layout: bottom navigation visible, desktop sidebar hidden
    check("mobile bottom nav visible", d.locator("nav[aria-label=Main]").last.is_visible())
    check("desktop sidebar hidden on mobile", not d.locator("aside").is_visible())

    # ---------------------------------------------------------------- driver flow
    d.get_by_role("button", name="Use my location").click()
    expect(d.get_by_test_id("coords")).to_contain_text("13.00670")
    check("live location shown", True, d.get_by_test_id("coords").inner_text())
    d.screenshot(path=str(SHOTS / "02-driver-location-mobile.png"))

    d.get_by_label("Current charge (number)").fill("12")
    d.get_by_label("Target charge (number)").fill("80")
    d.get_by_label("Must be done within (minutes)").fill("90")
    d.get_by_role("button", name="Find best charger").click()
    expect(d.get_by_test_id("station-card").first).to_be_visible(timeout=20000)
    cards = d.get_by_test_id("station-card")
    check("two ranked station cards", cards.count() == 2)
    check("farther Station B is ranked first", cards.first.get_attribute("data-station") == "B")
    check("explanation panel shown", len(d.get_by_test_id("explanation-text").inner_text()) > 40)
    d.screenshot(path=str(SHOTS / "03-driver-results-mobile.png"), full_page=True)

    # ---------------------------------------------------------------- operator in a second (desktop) browser
    op_ctx = browser.new_context(viewport={"width": 1360, "height": 900})
    o = op_ctx.new_page()
    sign_in(o, "operator@gridpulse.local", "Operator123!")
    o.wait_for_url("**/app/operator**")
    expect(o.get_by_text("Live", exact=True).first).to_be_visible(timeout=15000)
    check("operator dashboard connected live", True)
    check("desktop sidebar visible", o.locator("aside").is_visible())
    expect(o.get_by_test_id("operator-station")).to_have_count(2, timeout=15000)
    expect(o.get_by_test_id("chosen-station")).to_contain_text("Station B", timeout=15000)
    check("operator sees the latest decision (Station B) live", True)
    o.screenshot(path=str(SHOTS / "04-operator-overview.png"), full_page=True)

    # driver reserves -> operator sees it appear without reloading
    d.get_by_role("button", name=re.compile("Reserve at B")).click()
    expect(d.get_by_test_id("reservation-card").first).to_be_visible(timeout=15000)
    check("driver reservation confirmed", True)
    o.goto(f"{BASE}/app/operator?tab=reservations")
    expect(o.get_by_test_id("reservation-rows").get_by_text("Browser Driver").first).to_be_visible(timeout=15000)
    check("operator sees the new reservation (WebSocket)", True)

    # operator tightens Station A's limit -> live control command change
    o.goto(f"{BASE}/app/operator?tab=stations")
    a_card = o.locator('[data-testid="operator-station"][data-station="A"]')
    a_card.get_by_label("Site limit for A").fill("26")
    a_card.get_by_role("button", name="Apply").click()
    expect(a_card.get_by_text("REDUCE LOAD")).to_be_visible(timeout=15000)
    check("operator grid control changes the station command live", True)
    o.screenshot(path=str(SHOTS / "05-operator-stations.png"), full_page=True)

    o.goto(f"{BASE}/app/operator?tab=hardware")
    expect(o.get_by_text("Manual override").first).to_be_visible()
    check("hardware panel with placeholder manual override", o.get_by_role("button", name="NORMAL").first.is_disabled())
    o.screenshot(path=str(SHOTS / "06-operator-hardware.png"), full_page=True)

    # operator role cannot open the driver area
    o.goto(f"{BASE}/app/driver")
    o.wait_for_url("**/app/operator**")
    check("operator redirected away from /app/driver", "/app/operator" in o.url)

    # driver cancels -> operator's table updates live
    d.goto(f"{BASE}/app/driver?tab=reservations")
    d.get_by_role("button", name="Cancel").first.click()
    expect(d.get_by_test_id("reservation-card").first).to_have_attribute("data-status", "cancelled", timeout=15000)
    check("driver cancelled the reservation (live status)", True)
    o.goto(f"{BASE}/app/operator?tab=reservations")
    o.get_by_role("radio", name=re.compile("Recent history")).click()
    expect(o.get_by_test_id("reservation-rows").get_by_text("Browser Driver").first).to_be_visible(timeout=15000)
    check("operator sees it in history", True)

    # sign out clears the session
    d.get_by_role("button", name="Sign out").click()
    d.wait_for_url(BASE + "/")
    d.goto(f"{BASE}/app/driver")
    d.wait_for_url("**/signin")
    check("after sign out the app is protected again", "/signin" in d.url)

    # bad credentials show a clear error
    sign_in(d, email, "wrong-password1")
    expect(d.get_by_role("alert")).to_contain_text("Invalid email or password")
    check("wrong password shows an error", True)

    # reset the demo scenario for the next run
    o.goto(f"{BASE}/app/operator?tab=stations")
    o.on("dialog", lambda dlg: dlg.accept())
    o.get_by_role("button", name="Reset demo data").click()
    time.sleep(1)
    browser.close()

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
