"""GridPulse FastAPI application: JSON API, WebSocket, and the single-page web app on one URL."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

from .api import auth as auth_api, driver as driver_api, explain as explain_api, geo as geo_api
from .api import bulbs as bulbs_api, operator as operator_api, ws as ws_api
from .config import WEB_DIST, settings
from .db import SessionLocal, init_db
from .routers import control, dashboard, devices, drivers, reservations, stations, telemetry
from .seed import seed_database
from .services import auth_service, realtime, scheduler
from .services.control import refresh_control_state
from .services.devices import ensure_placeholder_devices


@asynccontextmanager
async def lifespan(_: FastAPI):
    for warning in settings.validate_for_runtime():
        print(f"[gridpulse] WARNING: {warning}")
    init_db()
    with SessionLocal() as db:
        seed_database(db, reset=False)  # only seeds an empty database
        ensure_placeholder_devices(db)  # also upgrades databases created before Milestone 3
        refresh_control_state(db)
        if settings.demo_users_enabled:
            auth_service.ensure_demo_users(db)

    tasks: list[asyncio.Task] = []
    if settings.scheduler_enabled:  # background clock + WebSocket broadcaster
        tasks = [asyncio.create_task(scheduler.run()), asyncio.create_task(realtime.broadcaster())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        realtime.manager.clear()


app = FastAPI(title="GridPulse", version="1.0.0", lifespan=lifespan)
if settings.cors_origin_list:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

# ---- authenticated product API + realtime ----------------------------------------------------------------
for _r in (auth_api, driver_api, operator_api, geo_api, explain_api, ws_api):
    app.include_router(_r.router)
app.include_router(bulbs_api.device)
app.include_router(bulbs_api.operator)

# ---- device protocol (device key) + legacy open API (only when LEGACY_API_ENABLED=true) ---------------------
for _r in (stations, drivers, reservations, dashboard, telemetry, control, devices):
    app.include_router(_r.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "GridPulse",
        "routing_mode": settings.routing_mode,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "demo_users": settings.demo_users_enabled,  # the sign-in page offers demo accounts in development
        "center": {"lat": settings.center_lat, "lon": settings.center_lon},
    }


# ---- single-page app (React build in web/dist) ---------------------------------------------------------------
_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>GridPulse</title>
<body style="font-family:system-ui;max-width:640px;margin:15vh auto;padding:0 20px;line-height:1.5">
<h1>GridPulse API is running</h1>
<p>The web app has not been built yet. From the project folder run:</p>
<pre style="background:#eee;padding:12px;border-radius:8px">cd web
npm install
npm run build</pre>
<p>then reload this page. API docs: <a href="/docs">/docs</a></p></body>"""


def _dist_file(relative: str) -> Path | None:
    """A file inside web/dist, or None (guards against path traversal)."""
    root = WEB_DIST.resolve()
    try:
        candidate = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    if root in candidate.parents and candidate.is_file():
        return candidate
    return None


def _index() -> Response:
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return HTMLResponse(_NOT_BUILT, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """Serve built assets, and index.html for every client-side route (/, /app, /app/driver, /app/operator, ...)."""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    if full_path:
        f = _dist_file(full_path)
        if f is not None:
            immutable = full_path.startswith("assets/")
            return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        if "." in full_path.rsplit("/", 1)[-1]:  # looks like a file request that does not exist
            raise HTTPException(404, "Not found")
    return _index()
