from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import legacy_guard
from ..services.dashboard import build_dashboard_state

router = APIRouter(tags=["dashboard"], dependencies=[Depends(legacy_guard)])


@router.get("/dashboard/state")
def dashboard_state(db: DbSession = Depends(get_db)):
    """Everything the operator dashboard renders, in one call (legacy, unauthenticated)."""
    return build_dashboard_state(db)
