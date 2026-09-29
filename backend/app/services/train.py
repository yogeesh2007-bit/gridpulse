"""Train context for the demo. ONLY the coach light node is live hardware; everything else here is seeded sample data
and is always labelled as such (`seeded: true`, `live: false`). Seeded items never pretend to be measurements."""
from __future__ import annotations

TRAIN = {"train_id": "DEMO-TRAIN-01", "name": "Demo train", "install_context": "train_demo"}
COACH = {"id": "C1", "name": "Coach C1"}

SEEDED_LIGHT_POINTS = [
    {"device_id": "aisle-02", "label": "Aisle light 2", "zone": "aisle", "state": "on"},
    {"device_id": "aisle-03", "label": "Aisle light 3", "zone": "aisle", "state": "on"},
    {"device_id": "vestibule-01", "label": "Vestibule light", "zone": "vestibule", "state": "off"},
]
SEEDED_SYSTEMS = [
    {"id": "door-c1-a", "label": "Entrance door A", "status": "closed"},
    {"id": "hvac-c1", "label": "Coach ventilation", "status": "auto"},
    {"id": "pa-c1", "label": "Passenger information", "status": "standby"},
]


def train_view(bulb_views: list[dict]) -> dict:
    live = [
        {"device_id": b["device_id"], "label": "Entrance light" if b["zone"] == "entrance_aisle" else b["zone"], "zone": b["zone"],
         "state": b["state"], "online": b["online"], "health": b["health"], "mode": b["mode"], "last_source": b["last_source"],
         "last_seen_at": b["last_seen_at"], "live": True, "seeded": False}
        for b in bulb_views if b["coach_id"] == COACH["id"]
    ]
    seeded = [{**p, "live": False, "seeded": True} for p in SEEDED_LIGHT_POINTS]
    systems = [{**s, "live": False, "seeded": True} for s in SEEDED_SYSTEMS]
    return {**TRAIN, "coach": COACH, "light_points": live + seeded, "systems": systems,
            "note": "Only nodes marked LIVE are real hardware. Seeded items are sample data."}
