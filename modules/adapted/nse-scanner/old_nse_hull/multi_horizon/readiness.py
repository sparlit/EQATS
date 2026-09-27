from __future__ import annotations

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


"""Explicit, non-promoting gate for Old NSE Hull shadow graduation."""

import json
from pathlib import Path

from .comparison import summarize


def assess(
    shadow_state_path: str | Path, walkforward_path: str | Path, historical_state_path: str | Path | None = None
) -> dict:
    """Return a transparent promotion decision; never changes any feature flag."""
    comparison = summarize(shadow_state_path)
    historical = (
        summarize(historical_state_path)
        if historical_state_path
        else {"sessions_observed": 0, "target_sessions": 20, "validation_ready": False}
    )
    walkforward_file = Path(walkforward_path)
    walkforward = json.loads(walkforward_file.read_text(encoding="utf-8")) if walkforward_file.exists() else {}
    blockers: list[str] = []
    if not historical["validation_ready"]:
        blockers.append(f"historical_replay_{historical['sessions_observed']}_of_{historical['target_sessions']}")
    if comparison["sessions_observed"] < 5:
        blockers.append(f"live_operational_sessions_{comparison['sessions_observed']}_of_5")
    if walkforward.get("status") != "COMPLETE" or not walkforward.get("observations"):
        blockers.append("walkforward_evidence_missing")
    return {
        "status": "READY_FOR_HUMAN_REVIEW" if not blockers else "BLOCKED",
        "automatic_promotion": False,
        "blockers": blockers,
        "comparison": comparison,
        "historical_replay": historical,
        "walkforward": {
            key: walkforward.get(key)
            for key in (
                "status",
                "observations",
                "samples",
                "mean_forward_return_pct",
                "median_forward_return_pct",
                "win_rate_pct",
            )
        },
    }
