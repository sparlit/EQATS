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
Market Stream (Kite WebSocket)
──────────────────────────────
Live tick feed from Zerodha Kite Connect WebSocket.
Used during market hours for real-time data ingestion.

Kite provides:
  - LTP, volume, OHLC, market depth
  - ~100-500ms latency
  - No historical tick data (use TrueData for that)
"""

import contextlib
from collections.abc import Callable
from datetime import datetime
from typing import List, Optional

from utils.logger import get_logger

from config.settings import KITE_ACCESS_TOKEN, KITE_API_KEY

logger = get_logger("market_stream")


class KiteStream:
    """Wraps Kite Connect WebSocket ticker for live market data."""

    def __init__(self):
        self._ticker = None
        self._callbacks: list[Callable] = []
        self._instrument_tokens: list[int] = []

    def connect(self, instrument_tokens: list[int]):
        """
        Connect to Kite WebSocket and subscribe to given instrument tokens.
        Instrument tokens map to specific NIFTY/BANKNIFTY option contracts.
        """
        self._instrument_tokens = instrument_tokens

        try:
            from kiteconnect import KiteTicker

            self._ticker = KiteTicker(KITE_API_KEY, KITE_ACCESS_TOKEN)
            self._ticker.on_ticks = self._on_ticks
            self._ticker.on_connect = self._on_connect
            self._ticker.on_close = self._on_close
            self._ticker.on_error = self._on_error

            logger.info("Connecting to Kite WebSocket...")
            self._ticker.connect(threaded=True)

        except ImportError:
            logger.warning("kiteconnect not installed or not configured. Live Kite stream unavailable.")
        except Exception as e:
            logger.exception(f"Kite WebSocket connection failed: {e}")

    def _on_connect(self, ws, response):
        logger.info("Kite WebSocket connected.")
        if self._instrument_tokens:
            ws.subscribe(self._instrument_tokens)
            ws.set_mode(ws.MODE_FULL, self._instrument_tokens)
            logger.info(f"Subscribed to {len(self._instrument_tokens)} instruments.")

    def _on_ticks(self, ws, ticks):
        for raw in ticks:
            tick = self._parse_kite_tick(raw)
            for cb in self._callbacks:
                try:
                    cb(tick)
                except Exception as e:
                    logger.exception(f"Tick callback error: {e}")

    def _on_close(self, ws, code, reason):
        logger.warning(f"Kite WebSocket closed: {code} – {reason}")

    def _on_error(self, ws, code, reason):
        logger.error(f"Kite WebSocket error: {code} – {reason}")

    def add_callback(self, callback: Callable):
        """Register a function to receive parsed tick dicts."""
        self._callbacks.append(callback)

    def disconnect(self):
        if self._ticker:
            with contextlib.suppress(Exception):
                self._ticker.close()
        logger.info("Kite WebSocket disconnected.")

    # ── Tick Parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_kite_tick(raw: dict) -> dict:
        """
        Convert Kite tick payload into our standard tick format.
        Kite MODE_FULL provides: ltp, volume, oi, depth, ohlc, etc.
        """
        depth = raw.get("depth", {})
        buy_depth = depth.get("buy", [{}])
        sell_depth = depth.get("sell", [{}])

        return {
            "timestamp": raw.get("exchange_timestamp", datetime.now()),
            "symbol": str(raw.get("instrument_token", "")),
            "price": float(raw.get("last_price", 0)),
            "volume": int(raw.get("volume_traded", 0)),
            "bid_price": float(buy_depth[0].get("price", 0)) if buy_depth else 0.0,
            "ask_price": float(sell_depth[0].get("price", 0)) if sell_depth else 0.0,
            "bid_qty": int(buy_depth[0].get("quantity", 0)) if buy_depth else 0,
            "ask_qty": int(sell_depth[0].get("quantity", 0)) if sell_depth else 0,
            "oi": int(raw.get("oi", 0)),
        }
