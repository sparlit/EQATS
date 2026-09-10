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


"""Independent Nifty 500 context for Old NSE + Hull shadow research."""

import sqlite3
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path

LOOKBACKS = {"1M": 22, "3M": 63, "6M": 126, "12M": 252}


def load_context(db_path: str | Path, features: pd.DataFrame) -> dict:
    """Return point-in-time benchmark returns and a simple breadth regime.

    No V2 module is imported.  The shared ``index_perf`` rows are read-only
    source data, just as Old NSE + Hull reads shared price snapshots.
    """
    if features.empty:
        return {"status": "AWAITING_BENCHMARK", "regime": "AWAITING_DATA", "benchmark_returns": {}}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            index = pd.read_sql_query(
                "SELECT date, close FROM index_perf WHERE lower(index_name) = lower('Nifty 500') ORDER BY date", conn
            )
    except (sqlite3.Error, pd.errors.DatabaseError):
        index = pd.DataFrame()
    if index.empty:
        return {"status": "AWAITING_BENCHMARK", "regime": "AWAITING_DATA", "benchmark_returns": {}}
    index["date"] = pd.to_datetime(index["date"])
    index["close"] = pd.to_numeric(index["close"], errors="coerce")
    index = index.dropna().drop_duplicates("date", keep="last").sort_values("date")
    as_of = pd.Timestamp(features["as_of_date"].iloc[0])
    index = index[index["date"] <= as_of]
    if len(index) < max(LOOKBACKS.values()) + 1 or index["date"].iloc[-1].date() != as_of.date():
        return {"status": "STALE_OR_INSUFFICIENT_BENCHMARK", "regime": "AWAITING_DATA", "benchmark_returns": {}}
    close = index["close"].reset_index(drop=True)
    returns = {horizon: float(close.iloc[-1] / close.iloc[-1 - days] - 1) for horizon, days in LOOKBACKS.items()}
    sma50, sma200 = close.rolling(50).mean().iloc[-1], close.rolling(200).mean().iloc[-1]
    breadth50 = float((features["close"] > features["sma50"]).mean() * 100)
    breadth200 = float((features["close"] > features["sma200"]).mean() * 100)
    if close.iloc[-1] > sma50 > sma200 and breadth50 >= 60 and breadth200 >= 50:
        regime = "RISK_ON"
    elif close.iloc[-1] < sma50 < sma200 and breadth50 <= 40 and breadth200 <= 35:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"
    return {
        "status": "CURRENT",
        "regime": regime,
        "benchmark": "Nifty 500",
        "benchmark_returns": returns,
        "breadth_above_50dma": round(breadth50, 2),
        "breadth_above_200dma": round(breadth200, 2),
    }
