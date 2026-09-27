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


"""Build and persist reproducible V2 market-regime snapshots."""

import json
import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING

import pandas as pd

from .indicators import hma
from .regime import classify_market_regime

if TYPE_CHECKING:
    from pathlib import Path


def compute_breadth(prices: pd.DataFrame, as_of: pd.Timestamp | None = None) -> dict:
    data = prices.copy()
    if data.empty:
        msg = "Price history is empty"
        raise ValueError(msg)
    if as_of is not None:
        data = data[data["trade_date"] <= as_of]
    data = data.sort_values(["symbol", "trade_date"])
    data["sma50"] = data.groupby("symbol")["close"].transform(lambda s: s.rolling(50).mean())
    data["sma200"] = data.groupby("symbol")["close"].transform(lambda s: s.rolling(200).mean())
    latest = data.groupby("symbol", as_index=False).tail(1)
    eligible50 = latest.dropna(subset=["sma50"])
    eligible200 = latest.dropna(subset=["sma200"])
    return {
        "as_of": latest["trade_date"].max().date().isoformat(),
        "eligible_50": len(eligible50),
        "eligible_200": len(eligible200),
        "pct_above_50": float((eligible50["close"] > eligible50["sma50"]).mean() * 100) if len(eligible50) else 0.0,
        "pct_above_200": float((eligible200["close"] > eligible200["sma200"]).mean() * 100)
        if len(eligible200)
        else 0.0,
    }


def build_market_snapshot(prices: pd.DataFrame, benchmark: pd.DataFrame) -> dict:
    breadth = compute_breadth(prices)
    bench = benchmark.sort_values("trade_date").copy()
    if len(bench) < 200:
        msg = "Benchmark requires at least 200 sessions"
        raise ValueError(msg)
    bench["trade_date"] = pd.to_datetime(bench["trade_date"])
    bench["hma55"] = hma(bench["close"], 55)
    bench["sma200"] = bench["close"].rolling(200).mean()
    last = bench.iloc[-1]
    as_of = pd.Timestamp(last["trade_date"])
    benchmark_for_regime = bench.set_index("trade_date")[["close"]]
    breadth_for_regime = pd.DataFrame(
        {
            "pct_above_50dma": [breadth["pct_above_50"]],
            "pct_above_200dma": [breadth["pct_above_200"]],
        },
        index=pd.DatetimeIndex([as_of]),
    )
    outcome = classify_market_regime(benchmark_for_regime, breadth_for_regime)
    reasons = [
        f"Benchmark is {'above' if outcome.benchmark_above_hma else 'below'} its HMA55",
        f"HMA55 is {'rising' if outcome.benchmark_hma_rising else 'falling'}",
        f"{outcome.breadth_above_50dma:.1f}% of eligible stocks are above their 50-day average",
        f"{outcome.breadth_above_200dma:.1f}% of eligible stocks are above their 200-day average",
    ]
    return {
        "trade_date": pd.Timestamp(last["trade_date"]).date().isoformat(),
        "regime": outcome.state,
        "score": outcome.score,
        "reasons": reasons,
        "breadth": breadth,
        "benchmark_close": float(last["close"]),
        "benchmark_hma55": float(last["hma55"]),
        "benchmark_sma200": float(last["sma200"]),
    }


def persist_market_snapshot(db_path: str | Path, snapshot: dict) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS market_regime_snapshots (
                trade_date TEXT PRIMARY KEY,
                regime TEXT NOT NULL,
                score REAL NOT NULL,
                pct_above_50 REAL NOT NULL,
                pct_above_200 REAL NOT NULL,
                benchmark_close REAL NOT NULL,
                benchmark_hma55 REAL NOT NULL,
                benchmark_sma200 REAL NOT NULL,
                reasons_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """INSERT INTO market_regime_snapshots (
                trade_date, regime, score, pct_above_50, pct_above_200,
                benchmark_close, benchmark_hma55, benchmark_sma200,
                reasons_json, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                regime=excluded.regime,
                score=excluded.score,
                pct_above_50=excluded.pct_above_50,
                pct_above_200=excluded.pct_above_200,
                benchmark_close=excluded.benchmark_close,
                benchmark_hma55=excluded.benchmark_hma55,
                benchmark_sma200=excluded.benchmark_sma200,
                reasons_json=excluded.reasons_json,
                snapshot_json=excluded.snapshot_json""",
            (
                snapshot["trade_date"],
                snapshot["regime"],
                snapshot["score"],
                snapshot["breadth"]["pct_above_50"],
                snapshot["breadth"]["pct_above_200"],
                snapshot["benchmark_close"],
                snapshot["benchmark_hma55"],
                snapshot["benchmark_sma200"],
                json.dumps(snapshot["reasons"]),
                json.dumps(snapshot),
            ),
        )
        conn.commit()
    finally:
        conn.close()
