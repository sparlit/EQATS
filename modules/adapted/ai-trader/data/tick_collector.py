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


"""
Tick Collector
──────────────
Central tick ingestion service. Receives ticks from any source
(Kite WebSocket, TrueData live stream, or mock generator) and:

  1. Writes raw ticks to tick_data table
  2. Notifies the aggregation engine for candle building
  3. Buffers ticks in-memory for micro-feature computation
"""

from collections.abc import Callable
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from utils.logger import get_logger

from database.db import write_df

logger = get_logger("tick_collector")


class TickCollector:
    """Collects ticks and persists them, with optional in-memory buffer."""

    def __init__(self, buffer_size: int = 500):
        self._buffer: list[dict] = []
        self._buffer_size = buffer_size
        self._listeners: list[Callable] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def on_tick(self, tick: dict):
        """
        Process a single tick. Expected keys:
          timestamp, symbol, price, volume,
          bid_price, ask_price, bid_qty, ask_qty, oi
        """
        tick.setdefault("timestamp", datetime.now())
        tick.setdefault("bid_price", None)
        tick.setdefault("ask_price", None)
        tick.setdefault("bid_qty", None)
        tick.setdefault("ask_qty", None)
        tick.setdefault("oi", None)

        self._buffer.append(tick)

        # Notify listeners (aggregation engine, micro-feature builder, etc.)
        for listener in self._listeners:
            try:
                listener(tick)
            except Exception as e:
                logger.exception(f"Tick listener error: {e}")

        # Flush buffer when full
        if len(self._buffer) >= self._buffer_size:
            self.flush()

    def flush(self):
        """Persist buffered ticks to the database."""
        if not self._buffer:
            return

        df = pd.DataFrame(self._buffer)
        cols = [
            "timestamp",
            "symbol",
            "price",
            "volume",
            "bid_price",
            "ask_price",
            "bid_qty",
            "ask_qty",
            "oi",
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = None

        try:
            write_df(df[cols], "tick_data")
            logger.info(f"Flushed {len(self._buffer)} ticks to database.")
        except Exception as e:
            logger.exception(f"Failed to flush ticks: {e}")

        self._buffer.clear()

    def add_listener(self, callback: Callable):
        """Register a callback that receives every tick dict."""
        self._listeners.append(callback)

    def get_buffer(self) -> list[dict]:
        """Return current in-memory buffer (for micro-feature computation)."""
        return list(self._buffer)

    def get_buffer_df(self, symbol: str | None = None) -> pd.DataFrame:
        """Return buffer as DataFrame, optionally filtered by symbol."""
        if not self._buffer:
            return pd.DataFrame()
        df = pd.DataFrame(self._buffer)
        if symbol:
            df = df[df["symbol"] == symbol]
        return df

    # ── Bulk Ingest (for loading historical ticks) ────────────────────────────

    def ingest_historical_ticks(self, df: pd.DataFrame):
        """
        Write a DataFrame of historical ticks directly to the database.
        Used when loading TrueData's 5-day tick history.
        """
        cols = [
            "timestamp",
            "symbol",
            "price",
            "volume",
            "bid_price",
            "ask_price",
            "bid_qty",
            "ask_qty",
            "oi",
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = None

        try:
            write_df(df[cols], "tick_data")
            logger.info(f"Ingested {len(df)} historical ticks.")
        except Exception as e:
            logger.exception(f"Failed to ingest historical ticks: {e}")
