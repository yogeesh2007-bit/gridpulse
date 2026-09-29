"""Runtime settings, loaded from environment variables and an optional .env file."""
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIST = WEB_DIR / "dist"
LEGACY_UI_DIR = PROJECT_ROOT / "legacy_ui"

DEV_OPERATOR_CODE = "operator-demo"  # only ever used in development


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
        env_ignore_empty=True,  # a blank `KEY=` line in .env means "use the default"
    )

    # ---- environment -----------------------------------------------------------------------------------
    app_env: str = "development"  # "development" | "production"
    gridpulse_db: str = ""
    cors_origins: str = ""  # comma separated; empty = same-origin only (the default single-URL deployment)

    # ---- auth --------------------------------------------------------------------------------------------
    jwt_secret: str = ""  # REQUIRED (>= 32 chars) in production; in development a local file secret is generated
    jwt_issuer: str = "gridpulse"
    access_token_minutes: float = 15
    refresh_token_days: int = 14
    refresh_reuse_grace_s: int = 10  # a just-rotated token replayed within this window (two tabs) is refused but does not revoke the session
    cookie_secure: bool = False  # set true when served over HTTPS
    operator_invite_code: str = ""  # required to sign up as an operator; dev default: operator-demo
    seed_demo_users: Optional[bool] = None  # default: on in development, off in production
    signin_max_attempts: int = 8  # per (ip, email) per window
    signin_window_s: int = 300

    # ---- legacy open endpoints (Milestone 1-4 dev tools, tests, scripts) ------------------------------------
    legacy_api_enabled: bool = False  # /stations, /seed, /reservations, /dashboard/state ... without auth
    device_api_key: str = ""  # if set, devices must send `X-Device-Key` (register/command/ack/telemetry)

    # ---- OpenRouter (optional, explanation text only) ------------------------------------------------------
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    openrouter_timeout_s: float = 25.0

    # ---- routing / geocoding -------------------------------------------------------------------------------
    routing_mode: str = "osrm"  # "osrm" or "haversine"
    osrm_url: str = "https://router.project-osrm.org"
    osrm_timeout_s: float = 3.0
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "GridPulse/1.0 (EV charging MVP; set NOMINATIM_USER_AGENT with your contact)"
    geocode_timeout_s: float = 4.0
    geocode_ttl_days: int = 30

    # ---- demo geography ------------------------------------------------------------------------------------
    center_lat: float = 13.0067
    center_lon: float = 80.0037

    # ---- background services -------------------------------------------------------------------------------
    scheduler_enabled: bool = True
    scheduler_tick_s: float = 2.0
    ws_tick_s: float = 2.0

    # ---- derived -------------------------------------------------------------------------------------------
    @property
    def db_path(self) -> str:
        return self.gridpulse_db or str(BACKEND_DIR / "gridpulse.db")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def demo_users_enabled(self) -> bool:
        return (not self.is_production) if self.seed_demo_users is None else self.seed_demo_users

    @property
    def effective_operator_code(self) -> str:
        return self.operator_invite_code or ("" if self.is_production else DEV_OPERATOR_CODE)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_runtime(self) -> list[str]:
        """Fail fast on unsafe production config; return warnings for development."""
        warnings: list[str] = []
        if self.is_production:
            problems = []
            if len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be set to at least 32 random characters")
            if not self.effective_operator_code:
                problems.append("OPERATOR_INVITE_CODE must be set (operators cannot self-register without it)")
            if self.legacy_api_enabled:
                problems.append("LEGACY_API_ENABLED must be false (it exposes unauthenticated control endpoints)")
            if problems:
                raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
            if not self.cookie_secure:
                warnings.append("COOKIE_SECURE is false: serve over HTTPS and set COOKIE_SECURE=true")
            if not self.device_api_key:
                warnings.append("DEVICE_API_KEY is empty: device endpoints are unauthenticated")
        else:
            if self.legacy_api_enabled:
                warnings.append("LEGACY_API_ENABLED=true: unauthenticated legacy endpoints are exposed (dev only)")
        return warnings


settings = Settings()
