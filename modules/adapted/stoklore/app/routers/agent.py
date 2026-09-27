import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""The agent page's API: background runs, and the flow diagram of what a run did.

Separate from chat.py because the two have different lifecycles. chat.py answers a request while
the browser waits; these start work that keeps going after the browser leaves, which needs a run
id, a status, and a feed you can rejoin. See app/services/agent_runs.py.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core import db
from app.deps import _sse
from app.schemas import AgentRunRequest
from app.services import agent_runs, workflow

router = APIRouter(tags=["agent"])


@router.get("/api/agent/runs")
def list_runs(session_id: str | None = None, status: str | None = None, limit: int = 50):
    """Every run, or one session's. `status=running` is what the sidebar's live dots read - a run
    belongs to the server, so the client can't know this from its own state."""
    return db.list_runs(session_id=session_id, status=status, limit=limit)


@router.post("/api/agent/runs")
def start_run(req: AgentRunRequest):
    prompt = req.message.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="nothing to send")
    model = req.model or db.get_session_model(req.session_id) or db.get_active_model()
    if req.model:
        db.ensure_session(req.session_id)
        db.set_session_model(req.session_id, model)
    run_id = agent_runs.start(req.session_id, prompt, model, req.history or [])
    return {"run_id": run_id, "model": model}


@router.get("/api/agent/runs/{run_id}/events")
def run_events(run_id: str):
    """Replay-then-follow SSE. Safe to open more than once and safe to reopen after a refresh -
    it always starts from the beginning of the run, not from the moment you connected."""

    def stream():
        for event in agent_runs.follow(run_id):
            yield _sse(event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/api/agent/runs/{run_id}/workflow")
def run_workflow(run_id: str):
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    return workflow.build(run, db.list_tool_calls(run_id))


@router.get("/api/agent/sessions/{session_id}/workflow")
def session_workflow(session_id: str):
    """The session's most recent run, which is what the Workflow tab opens onto - asking for "the
    diagram for this chat" means the last thing it did."""
    runs = db.list_runs(session_id=session_id, limit=1)
    if not runs:
        return {"nodes": [], "edges": [], "run": None}
    run = runs[0]
    return {**workflow.build(run, db.list_tool_calls(run["id"])), "run": run}
