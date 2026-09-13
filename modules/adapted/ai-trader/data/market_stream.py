import datetime
from datetime import datetime as dt
from typing import TYPE_CHECKING, List, Optional

import pytz

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    from utils.logger import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)


try:
    from config.settings import KITE_ACCESS_TOKEN, KITE_API_KEY
except ImportError:
    KITE_ACCESS_TOKEN = ""
    KITE_API_KEY = ""

logger = get_logger("market_stream")


def is_ist_market_session_active(dt: dt | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else dt.now(ist)
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
            self._parse_kite_tick(raw)
            # Process tick as needed

    def _parse_kite_tick(self, raw: dict) -> dict:
        """Parse raw Kite tick into standardized format."""
        return raw

    def _on_close(self, ws, code, reason):
        logger.info(f"Kite WebSocket closed: {code} - {reason}")

    def _on_error(self, ws, code, reason):
        logger.error(f"Kite WebSocket error: {code} - {reason}")
