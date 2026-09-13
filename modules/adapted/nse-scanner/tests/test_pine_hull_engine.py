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


import sqlite3
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from pine_hull.engine import PineConfig, load_state, pine_metrics, run_daily
from pine_hull.preview import render_daily_signals

if TYPE_CHECKING:
    from pathlib import Path


def _frame(rows: int = 330, *, final_low: float | None = None, end: float = 260.0) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=rows)
    close = pd.Series(np.linspace(100.0, end, rows))
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "open": close - 0.3,
            "high": close + 3.0,
            "low": close - 3.0,
            "close": close,
            "volume": 150_000,
        }
    )
    if final_low is not None:
        frame.loc[frame.index[-1], "low"] = final_low
    return frame


def _database(path: Path, frame: pd.DataFrame) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE daily_prices_v2 (
            symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL
        )""")
        loaded = frame.assign(symbol="PINE")[["symbol", "trade_date", "open", "high", "low", "close", "volume"]].copy()
        loaded["trade_date"] = loaded["trade_date"].dt.strftime("%Y-%m-%d")
        loaded.to_sql("daily_prices_v2", conn, if_exists="append", index=False)


def test_pine_core_reports_ready_for_clean_uptrend() -> None:
    metrics = pine_metrics(_frame(end=200.0))
    assert metrics["available"] is True
    assert metrics["daily_bullish"] is True
    assert metrics["weekly_bullish"] is True
    assert metrics["state"] == "READY"
    assert metrics["initial_stop"] < metrics["close"]


def test_pine_daily_state_is_independent_and_freezes_entry_levels(tmp_path: Path) -> None:
    db_path, state_path = tmp_path / "prices.db", tmp_path / "pine_state.json"
    _database(db_path, _frame(end=200.0))
    result = run_daily(db_path, state_path=state_path, config=PineConfig(capital_base=300_000.0))
    assert len(result["created"]) == 1
    position = result["created"][0]
    assert position["entry"] == 200.0
    assert position["target1"] > position["entry"]
    saved = load_state(state_path)
    assert saved["positions"][0]["trade_id"].startswith("PINE-")
    assert saved["positions"][0]["state"] == "OPEN"


def test_pine_signal_message_matches_compact_daily_candidate_style() -> None:
    result = {
        "trade_date": "2026-08-07",
        "created": [
            {
                "symbol": "RELIANCE",
                "entry": 1500.0,
                "initial_stop": 1450.0,
                "target1": 1575.0,
                "target2": 1650.0,
                "htf_weekly_bullish": True,
            }
        ],
        "watch": [{"symbol": "TCS", "score": 82.0, "overextended": False, "chop": False, "rotational": False}],
    }
    message = render_daily_signals(result)
    assert "PINE HULL — DAILY WATCHLIST" in message
    assert "NSE%3ARELIANCE" in message
    assert "Watch for entry" in message
    assert "Early watchlist" in message
    assert "Planned entry: ₹1,500.00–" in message
    assert "SL ₹1,450.00 | T1 ₹1,575.00 | T2 ₹1,650.00" in message
    assert "Evidence: Hull pullback continuation • Daily Hull bullish" in message
    assert "More watchlist setups" in message
    assert "NSE%3ATCS" in message
