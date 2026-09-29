"""SQLite engine, session factory and helpers."""
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    """WAL lets the background scheduler write while requests read; busy_timeout avoids 'database is locked'."""
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


def utcnow() -> datetime:
    """Naive UTC 'now'. All datetimes in the DB are naive UTC; the API adds a 'Z'."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_columns() -> None:
    """Tiny forward-only migration so an existing Milestone 1 database keeps working."""
    wanted = {
        "stations": {"device_id": "VARCHAR(64)"},
        "driver_requests": {"deadline_at": "DATETIME", "user_id": "INTEGER"},
        "bulb_devices": {
            "device_type": "VARCHAR(30) DEFAULT 'coach_light'", "coach_id": "VARCHAR(10) DEFAULT 'C1'",
            "zone": "VARCHAR(30) DEFAULT 'entrance_aisle'", "voltage_type": "VARCHAR(40) DEFAULT '12V DC relay-switched load'",
            "install_context": "VARCHAR(30) DEFAULT 'train_demo'", "mode": "VARCHAR(20) DEFAULT 'idle'",
        },
        "telemetry": {
            "source": "VARCHAR(12) DEFAULT 'real'", "dry_run": "BOOLEAN DEFAULT 0",
            "sensor_status": "VARCHAR(16) DEFAULT 'ok'", "event": "VARCHAR(32)", "local_override": "BOOLEAN",
        },
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            have = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in cols.items():
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        # Milestone 1 databases were seeded without a device id for the physical rig.
        conn.exec_driver_sql(
            "UPDATE stations SET device_id = 'esp32-station-a' WHERE code = 'A' AND device_id IS NULL"
        )


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
