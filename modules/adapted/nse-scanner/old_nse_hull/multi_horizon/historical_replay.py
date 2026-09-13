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


"""Point-in-time 20-session replay using the existing shared EOD database."""


from typing import TYPE_CHECKING

import pandas as pd

from old_nse_hull.discovery import discover

from .comparison import summarize
from .engine import run_shadow

if TYPE_CHECKING:
    from pathlib import Path


def run(prices: pd.DataFrame, db_path: str | Path, state_path: str | Path, sessions: int = 20) -> dict:
    """Replay prior completed sessions without fetching or mutating market data."""
    dates = sorted(pd.to_datetime(prices["trade_date"]).dropna().unique())[-sessions:]
    completed: list[str] = []
    for date in dates:
        history = prices[pd.to_datetime(prices["trade_date"]) <= date]
        baseline = discover(history).shortlist
        shadow = run_shadow(history, db_path, baseline["symbol"].astype(str).tolist(), state_path)
        completed.append(shadow["as_of_date"])
    return {
        "mode": "HISTORICAL_REPLAY",
        "sessions_requested": sessions,
        "sessions_completed": len(completed),
        "as_of_dates": completed,
        "comparison_summary": summarize(state_path),
    }
