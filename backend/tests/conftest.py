import os
import tempfile

# Must be set before the app is imported: isolated DB, offline routing, no LLM key, hermetic auth settings.
_tmp = tempfile.mkdtemp(prefix="gridpulse-test-")
os.environ["GRIDPULSE_DB"] = os.path.join(_tmp, "test.db")
os.environ["ROUTING_MODE"] = "haversine"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["APP_ENV"] = "development"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-0123456789"
os.environ["LEGACY_API_ENABLED"] = "true"  # the pre-auth JSON API is still covered by its own tests
os.environ["SCHEDULER_ENABLED"] = "false"  # tests drive the state themselves; realtime tests start it explicitly
os.environ["DEVICE_API_KEY"] = ""
os.environ["OPERATOR_INVITE_CODE"] = "test-operator-code"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import settings  # noqa: E402

# Blank env vars are ignored by the settings loader, so pin these directly: tests must never use a real key
# from a developer's .env, and must not depend on their device key or database.
settings.openrouter_api_key = ""
settings.device_api_key = ""
settings.legacy_api_enabled = True
settings.scheduler_enabled = False


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/seed", params={"reset": True})
        yield c


# ---- authenticated helpers -------------------------------------------------------------------------------
def _signin(c: TestClient, email: str, password: str) -> dict:
    r = c.post("/api/auth/signin", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def operator(client):
    """A TestClient-bound operator session: returns (auth headers, user)."""
    data = _signin(client, "operator@gridpulse.local", "Operator123!")
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]


@pytest.fixture()
def driver(client):
    data = _signin(client, "driver@gridpulse.local", "Driver123!")
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]
