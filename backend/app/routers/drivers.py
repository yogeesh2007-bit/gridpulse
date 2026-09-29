"""Legacy, unauthenticated driver endpoints (only when LEGACY_API_ENABLED=true). Use /api/driver in the app."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import legacy_guard
from ..models import DriverRequest
from ..schemas import (
    DriverRequestIn,
    DriverRequestOut,
    ExplanationIn,
    ExplanationOut,
    LocationUpdateIn,
    RecommendationIn,
)
from ..services import driver_flow as flow

router = APIRouter(tags=["legacy"], dependencies=[Depends(legacy_guard)])


@router.post("/drivers/request", response_model=DriverRequestOut)
def create_driver_request(body: DriverRequestIn, db: DbSession = Depends(get_db)):
    """Store a driver's charging need (spec names `lat, lng, soc, target_soc, deadline` are accepted)."""
    return flow.create_driver_request(db, body)


@router.post("/recommendation")
def recommendation(body: RecommendationIn, db: DbSession = Depends(get_db)):
    """Rank all stations for a stored request: chosen_station, ranking, predicted wait / travel / charge
    time, score breakdown and explanation."""
    req = db.get(DriverRequest, body.request_id)
    if not req:
        raise HTTPException(404, "Driver request not found")
    return flow.run_recommendation(db, req)


@router.post("/recommend")
def recommend(body: DriverRequestIn, db: DbSession = Depends(get_db)):
    """One call: store the driver's request and return the recommendation (same output as /recommendation)."""
    return flow.run_recommendation(db, flow.create_driver_request(db, body))


@router.post("/explanation", response_model=ExplanationOut)
def explanation(body: ExplanationIn, db: DbSession = Depends(get_db)):
    """Optionally rephrase the rule-based explanation with OpenRouter. Always returns usable text."""
    req = db.get(DriverRequest, body.request_id)
    try:
        if not req:
            raise LookupError
        return flow.explain_request(db, req)
    except LookupError:
        raise HTTPException(404, "No recommendation stored for this request")


@router.post("/driver/location/update")
def driver_location_update(body: LocationUpdateIn, db: DbSession = Depends(get_db)):
    """Store a live position for a driver and return fresh route ETAs to every station."""
    req = db.get(DriverRequest, body.request_id)
    if not req:
        raise HTTPException(404, "Driver request not found")
    return flow.update_live_location(db, req, body.lat, body.lon, body.accuracy_m, body.source)
