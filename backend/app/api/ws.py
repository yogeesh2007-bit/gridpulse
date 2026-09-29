"""WebSocket endpoint: authenticated live updates (see services/realtime.py for the message formats)."""
import json

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from ..db import SessionLocal
from ..deps import user_from_access_token
from ..services import realtime
from ..services.realtime import Connection, WS_TOKEN_EXPIRED, manager

router = APIRouter(tags=["realtime"])


def _authenticate(token: str):
    with SessionLocal() as db:
        user, payload = user_from_access_token(db, token)
        return {"id": user.id, "role": user.role, "name": user.name}, float(payload["exp"])


@router.websocket("/api/ws")
async def live(ws: WebSocket, token: str = Query("")):
    """Connect with `/api/ws?token=<access token>`. Operators get `state` messages; drivers get `driver` messages.
    Send the text `ping` to receive `{"type": "pong"}`."""
    await ws.accept()
    try:
        user, expires_at = await run_in_threadpool(_authenticate, token)
    except HTTPException as e:
        await ws.send_text(json.dumps({"type": "error", "detail": e.detail}))
        await ws.close(code=WS_TOKEN_EXPIRED, reason=str(e.detail))
        return
    manager.add(Connection(ws=ws, user_id=user["id"], role=user["role"], expires_at=expires_at))
    await ws.send_text(json.dumps({"type": "hello", "role": user["role"], "name": user["name"]}))
    realtime.poke()  # send the first snapshot immediately
    try:
        while True:
            text = await ws.receive_text()
            if text == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(ws)
