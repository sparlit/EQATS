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


import pytest
from src.autonomous_intelligence import AutonomousCycle, AutonomousTask


def test_actionable_task_requires_evidence():
    with pytest.raises(ValueError, match="require evidence"):
        AutonomousTask(task_id="t1", symbol="INFY", action="RESEARCH")


def test_automated_execution_is_rejected():
    task = AutonomousTask(
        task_id="t1",
        symbol="INFY",
        action="ALERT",
        evidence_refs=["evidence-1"],
    )
    with pytest.raises(ValueError, match="not permitted"):
        AutonomousCycle(
            cycle_id="c1",
            generated_at="2026-07-31T00:00:00Z",
            tasks=[task],
            execution_enabled=True,
        )


def test_valid_observation_cycle():
    task = AutonomousTask(
        task_id="t1",
        symbol="INFY",
        action="OBSERVE",
        evidence_refs=["evidence-1"],
        status="READY",
    )
    cycle = AutonomousCycle(
        cycle_id="c1",
        generated_at="2026-07-31T00:00:00Z",
        tasks=[task],
    )
    assert cycle.execution_enabled is False
