"""Geo helpers: reverse geocoding (cached Nominatim)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services import geocode

router = APIRouter(prefix="/api/geo", tags=["geo"])


@router.get("/reverse")
def reverse(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    _user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    """Readable place name for a position. Always answers 200: on any upstream problem it returns the coordinates
    with `source: "fallback"`."""
    return geocode.reverse_geocode(db, lat, lon)
