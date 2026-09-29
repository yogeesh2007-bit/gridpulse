"""Optional AI explanation layer (OpenRouter). It only rewrites an already-computed decision into friendly text."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import get_current_user
from ..models import DriverRequest, User
from ..schemas import ExplanationIn, ExplanationOut
from ..services import driver_flow as flow, realtime

router = APIRouter(prefix="/api", tags=["explain"])


@router.post("/explain", response_model=ExplanationOut)
def explain(body: ExplanationIn, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    """Convert the structured decision for a request into user-friendly text.

    Uses OpenRouter (`OPENROUTER_MODEL`, default `openrouter/free`) when `OPENROUTER_API_KEY` is set; on any failure - or
    when the model's text fails the grounding checks - the deterministic explanation is returned instead. Drivers can
    only explain their own requests; operators can explain any.
    """
    req = db.get(DriverRequest, body.request_id)
    if req is None or (user.role != "operator" and req.user_id != user.id):
        raise HTTPException(404, "No recommendation stored for this request")
    try:
        out = flow.explain_request(db, req)
    except LookupError:
        raise HTTPException(404, "No recommendation stored for this request")
    realtime.poke()
    return out
