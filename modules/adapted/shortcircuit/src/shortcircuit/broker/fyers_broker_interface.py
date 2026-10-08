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
Unified Broker Interface with WebSocket-First Architecture.

Design:
- WebSocket connections for real-time data (order updates, position changes, ticks)
- REST API as fallback for operations not supported by WebSocket
- Transparent caching layer to minimize REST API calls
- Thread-safe, async-first design

Usage (from shortcircuit.execution.order_manager):
    broker = FyersBrokerInterface(access_token, db_manager)
    await broker.initialize()
    order_id = await broker.place_order(symbol='NSE:SBIN-EQ', side='SELL', qty=100)
    await broker.wait_for_fill(order_id)   # resolves on a WS push, not by polling
"""

import asyncio
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import requests
from shortcircuit import config
from shortcircuit.broker.fyers_connect import ASYNC_CALL_TIMEOUT, ASYNC_RETRIED_TIMEOUT
from shortcircuit.broker.rest_limiter import Priority, rest_limiter
from shortcircuit.marketdata.market_utils import is_market_hours as is_market_hours_ist

logger = logging.getLogger(__name__)

# WebSocket imports, with a graceful fallback when the SDK is absent.

_WS_AVAILABLE = False
_data_ws_module = None
_order_ws_module = None

try:
    from fyers_apiv3.FyersWebsocket import data_ws as _data_ws_module
    from fyers_apiv3.FyersWebsocket import order_ws as _order_ws_module

    _WS_AVAILABLE = True
    logger.info("✅ Fyers WebSocket modules loaded (setuptools==79.0.1 confirmed)")
except ImportError as e:
    logger.critical(
        f"❌ WebSocket import failed: {e}\n"
        f"   Fix: pip install setuptools==79.0.1\n"
        f"   Bot will run in REST-only mode."
    )

import contextlib

from fyers_apiv3 import fyersModel


class OrderPlacementTimeout(Exception):
    """
    The place_order HTTP call timed out.

    Deliberately distinct from a rejection: a timeout means the order's fate is
    UNKNOWN. It may be live at the exchange. Callers must reconcile against the
    orderbook before retrying, or they risk double-entering a position.
    """


class PositionFetchError(Exception):
    """
    The broker could not tell us what positions are open.

    Deliberately distinct from an empty list: `[]` means "verified flat", this
    means "unknown". Returning `[]` for both is how NSE:GRAPHITE-EQ was left
    naked on 2026-09-09 — safe_exit cancelled the stop, read a rate-limited
    fetch as "already closed", and never placed the cover order.

    Anything that decides whether a position still exists must catch this and
    treat it as "still open until proven otherwise".
    """


class FyersOrderStatus(int, Enum):
    """
    Fyers API v3 numeric order status codes.

    Verified against this account's own session logs, where the observed
    distribution was: 4 (353x), 6 (269x), 2 (134x), 1 (37x), 5 (29x).

    NOTE: 4 is TRANSIT (order en route to the exchange), not "partial fill".
    The previous status map labelled it PARTIAL, which made any wait-for-fill
    that returned on the first update resolve on a not-yet-live order.
    """

    CANCELLED = 1
    FILLED = 2
    RESERVED = 3  # documented as "for future use"
    TRANSIT = 4
    REJECTED = 5
    PENDING = 6

    @classmethod
    def coerce(cls, raw) -> Optional["FyersOrderStatus"]:
        """Accept int, numeric string, or enum. Returns None when unrecognised."""
        if isinstance(raw, cls):
            return raw
        try:
            return cls(int(raw))
        except (TypeError, ValueError):
            return None


# An order in one of these states will never change again — safe to stop waiting.
TERMINAL_ORDER_STATUSES = frozenset(
    {
        FyersOrderStatus.FILLED,
        FyersOrderStatus.CANCELLED,
        FyersOrderStatus.REJECTED,
    }
)

# States meaning "still working" — a waiter must keep waiting.
LIVE_ORDER_STATUSES = frozenset(
    {
        FyersOrderStatus.TRANSIT,
        FyersOrderStatus.PENDING,
    }
)


def unwrap_ws_payload(message: Any, key: str) -> dict | None:
    """
    Unwrap a Fyers order-socket envelope.

    The SDK's __parse_* methods return the payload nested under a type key:

        {'s': 'ok', 'orders':    {...}}
        {'s': 'ok', 'positions': {...}}
        {'s': 'ok', 'trades':    {...}}

    Reading fields off the envelope's top level (message.get('id')) silently
    yields None for every field — the defect that made every fill fall back to
    the 15s REST timeout path. Confirmed against the installed SDK's
    FyersWebsocket/order_ws.py and its map.json field mappers.

    Tolerates a already-flat payload so this stays correct if the SDK ever stops
    wrapping, and returns None for anything unusable.
    """
    if not isinstance(message, dict):
        return None

    payload = message.get(key)
    if isinstance(payload, dict) and payload:
        return payload

    # Already unwrapped? Envelopes carry only 's' plus the type key; a real
    # payload carries identifying fields.
    if any(f in message for f in ("id", "symbol", "orderNumber", "netQty")):
        return message

    return None


class OrderUpdate:
    """Data class for order updates from WebSocket."""

    def __init__(self, data: dict):
        self.order_id = data.get("id")
        self.symbol = data.get("symbol")
        self.status = data.get("status")  # numeric Fyers code, or mapped string
        self.filled_qty = data.get("filledQty", 0) or 0
        self.remaining_qty = data.get("remainingQuantity", 0) or 0
        self.avg_price = data.get("tradedPrice", 0) or 0
        self.limit_price = data.get("limitPrice", 0) or 0
        self.stop_price = data.get("stopPrice", 0) or 0
        self.message = data.get("message", "")
        self.timestamp = datetime.now(UTC)
        self.raw_data = data


class PositionUpdate:
    """Data class for position updates from WebSocket."""

    def __init__(self, data: dict):
        self.symbol = data.get("symbol")
        self.net_qty = data.get("netQty", 0)
        self.avg_price = data.get("avgPrice", 0)
        self.realized_pnl = data.get("realized_profit", 0)
        self.unrealized_pnl = data.get("unrealized_profit", 0)
        self.timestamp = datetime.now(UTC)
        self.raw_data = data


class TickData:
    """Data class for market tick data from WebSocket."""

    def __init__(self, data: dict):
        self.symbol = data.get("symbol")
        # Fyers V3 uses 'lp' for LTP in ticks, and 'ltp' in some SDK-parsed formats.
        self.ltp = data.get("ltp", data.get("lp", 0)) or 0

        # Volume: 'vol_traded_today' (Mode Full) or 'v' (Mode SymbolUpdate)
        self.volume = data.get("vol_traded_today", data.get("v", data.get("volume", 0))) or 0

        self.bid = data.get("bid", self.ltp) or 0
        self.ask = data.get("ask", self.ltp) or 0

        # OHLC: 'h'/'l'/'o' vs 'high_price'/'low_price'/'open_price'
        self.open = data.get("open_price", data.get("o", 0)) or 0
        self.high = data.get("high_price", data.get("h", 0)) or 0
        self.low = data.get("low_price", data.get("l", 0)) or 0
        self.prev_close = data.get("prev_close_price", data.get("pc", 0)) or 0

        self.timestamp = datetime.now(UTC)
        self.raw_data = data


class CacheEntrySource(Enum):
    WS_TICK = "ws"
    REST_SEED = "rest"


class BrokerHealthState(Enum):
    """
    Phase PRD-WS: Formal broker health state machine.
    Single authority for all health classification.
    """

    UNINITIALIZED = "UNINITIALIZED"
    CONNECTING = "CONNECTING"
    PRIMING = "PRIMING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    SEVERE_DEGRADED = "SEVERE_DEGRADED"
    REPRIME_PENDING = "REPRIME_PENDING"
    FULL_RECONNECT_PENDING = "FULL_RECONNECT_PENDING"
    HYBRID_REST_MODE = "HYBRID_REST_MODE"
    RECOVERED = "RECOVERED"
    UNRECOVERABLE = "UNRECOVERABLE"


@dataclass
class WSHealth:
    """Per-socket health tracking — data WS and order WS tracked independently."""

    connected: bool = False
    last_event_time: float = 0.0
    reconnect_count: int = 0
    last_close_reason: str = ""
    last_error: str = ""


@dataclass
class CacheEntry:
    last_price: float
    volume: float
    ch_oc: float
    oi: float
    bid: float
    ask: float
    open_price: float
    high_price: float
    prev_close: float
    last_time: float
    source: CacheEntrySource
    tick_count: int = 0


@dataclass
class Candle:
    """Data class for a single OHLCV candle."""

    symbol: str
    epoch: int  # Unix timestamp of the start of the candle
    open: float
    high: float
    low: float
    close: float
    volume: float
    datetime: datetime


class MinuteCandleAggregator:
    """
    Aggregates raw WebSocket ticks into 1-minute OHLCV candles.
    Maintains a rolling buffer for the Analyzer to consume.
    """

    def __init__(self, max_candles: int = 500):
        self.max_candles = max_candles
        self.history: dict[str, deque[Candle]] = {}  # symbol -> deque[Candle]
        self.current_candles: dict[str, Candle] = {}  # symbol -> partially formed Candle
        self.minute_start_volume: dict[
            str, float
        ] = {}  # symbol -> volume at start of current minute

        # Real-time Slope Metrics
        self.vwap_history: dict[str, deque[float]] = {}  # symbol -> deque[float] (VWAP values)
        self._lock = threading.Lock()

    def update(self, tick: TickData, timestamp: float | None = None):
        """Processes a new tick and updates/finalizes candles."""
        symbol = tick.symbol
        if not symbol or not tick.ltp:
            return

        # Calculate minute start (epoch)
        now_ts = int(timestamp if timestamp is not None else time.time())
        minute_start = (now_ts // 60) * 60

        with self._lock:
            current = self.current_candles.get(symbol)

            if current and current.epoch == minute_start:
                # Update existing candle
                current.high = max(current.high, tick.ltp)
                current.low = min(current.low, tick.ltp)
                current.close = tick.ltp

                # Fyers ticks have cumulative volume. Periodic volume = Total - Start of Minute.
                start_vol = self.minute_start_volume.get(symbol, tick.volume)
                current.volume = max(0, tick.volume - start_vol)
            else:
                # Finalize old candle if it exists
                if current:
                    if symbol not in self.history:
                        self.history[symbol] = deque(maxlen=self.max_candles)
                    self.history[symbol].append(current)

                self.minute_start_volume[symbol] = tick.volume

                # Update rolling VWAP history for slope calculation
                if current:
                    if symbol not in self.vwap_history:
                        self.vwap_history[symbol] = deque(maxlen=60)  # Store 1 hour of VWAPs

                    # Calculate VWAP for the finalized candle
                    (current.high + current.low + current.close) / 3
                    # The slope only needs a consistent series, so the finalized
                    # close stands in for the candle's VWAP here.
                    self.vwap_history[symbol].append(current.close)

                new_candle = Candle(
                    symbol=symbol,
                    epoch=minute_start,
                    open=tick.ltp,
                    high=tick.ltp,
                    low=tick.ltp,
                    close=tick.ltp,
                    volume=0,  # First tick of the minute
                    datetime=datetime.fromtimestamp(minute_start),
                )
                self.current_candles[symbol] = new_candle

    def get_candles(self, symbol: str, n: int = 100) -> list[Candle]:
        """Returns the last N candles for a symbol, including the current one."""
        with self._lock:
            hist = list(self.history.get(symbol, []))
            current = self.current_candles.get(symbol)

            result = hist
            if current:
                # Need as a new list to avoid modifying history deque
                result = list(hist) + [current]

            return result[-n:]

    def get_vwap_slope(self, symbol: str, window: int = 30) -> float:
        """
        Calculate Slope on-the-fly from memory cache.
        Returns Normalized Linear Regression Slope (dy/dx).
        """
        import numpy as np

        with self._lock:
            history = self.vwap_history.get(symbol)
            if not history or len(history) < window:
                # Fallback: calculate from Candle history if vwap_history not yet primed
                candles = list(self.history.get(symbol, []))
                current = self.current_candles.get(symbol)
                if current:
                    candles.append(current)

                if len(candles) < 5:
                    return 0.0  # Not enough for any trend

                y = np.array([c.close for c in candles[-window:]])
            else:
                y = np.array(list(history)[-window:])

            x = np.arange(len(y))
            if len(y) < 2:
                return 0.0

            # Linear Regression
            slope, _ = np.polyfit(x, y, 1)

            # Normalize slope as % of current price (to make it symbol-invariant)
            current_price = y[-1]
            if current_price > 0:
                normalized_slope = (slope / current_price) * 1000  # Scaling factor for readability
                return round(normalized_slope, 4)

            return 0.0


class FyersBrokerInterface:
    """
    Unified broker interface with WebSocket-first architecture.

    Features:
    - WebSocket for real-time order/position/tick updates (10-50ms latency)
    - REST API for order placement and fallback queries
    - Intelligent caching to minimize REST calls (53k/day → 165/day)
    - Rate limit enforcement (prevents API blocks)
    - Auto-reconnect on WebSocket disconnect
    """

    def __init__(self, access_token: str, client_id: str, db_manager, emergency_logger):
        self.access_token = access_token
        self.client_id = client_id
        self.db = db_manager
        self.emergency_logger = emergency_logger

        # Ensure log directories exist
        import os

        os.makedirs("logs/fyers_rest", exist_ok=True)
        os.makedirs("logs/fyers_order_ws", exist_ok=True)
        os.makedirs("logs/fyers_data_ws", exist_ok=True)

        # REST API client (for order placement)
        self.rest_client = fyersModel.FyersModel(
            client_id=client_id, token=access_token, log_path="logs/fyers_rest"
        )

        # Connection pooling and a hard timeout. Testing hasattr(client, 'session')
        # is always False on FyersModel, so the old pool fix never applied and every
        # REST call ran untimed. harden_fyers_session resolves the real session.
        from shortcircuit.broker.fyers_connect import harden_fyers_session

        harden_fyers_session(self.rest_client, label="broker rest_client")

        # WebSocket clients
        self.data_ws = None  # Market data WebSocket
        self.order_ws = None  # Order update WebSocket

        # WebSocket state
        self.ws_connected = False
        self.data_ws_connected = False
        self.order_ws_connected = False
        self.ws_reconnecting = False

        # Local Candle Engine
        self.aggregator = MinuteCandleAggregator(
            max_candles=getattr(config, "P82_MAX_LOCAL_CANDLES", 500)
        )

        # Real-time caches (updated by WebSocket)
        self.tick_cache: dict[str, deque] = {}  # symbol -> deque of TickData
        self.position_cache: dict[str, PositionUpdate] = {}  # symbol -> PositionUpdate
        self.order_status_cache: dict[str, OrderUpdate] = {}  # order_id -> OrderUpdate

        # Event waiters (for async notification)
        self.order_fill_events: dict[str, asyncio.Event] = {}  # order_id -> asyncio.Event
        # Ids of every order this process placed. Anything working at the broker
        # that is NOT in here was placed outside the bot — which is the only
        # honest definition of a manual order.
        self.bot_order_ids: set[str] = set()
        self.position_change_events = defaultdict(asyncio.Event)

        # Callbacks (for strategy integration)
        self.on_tick_callbacks = []  # List[Callable[[TickData], None]]
        self.on_order_update_callbacks = []
        self.on_position_update_callbacks = []

        # Rate limiting
        self.api_calls = defaultdict(deque)  # endpoint -> deque of timestamps
        self.rate_limits = {
            "place_order": (10, 1.0),  # 10 calls per second
            "cancel_order": (10, 1.0),
            "get_positions": (1, 1.0),  # 1 call per second (strict limit)
            "get_order_status": (5, 1.0),
            "get_quotes": (5, 1.0),
            "get_market_depth": (1, 1.0),
        }

        # Watchlist (symbols to subscribe)
        self.subscribed_symbols: set[str] = set()

        # Order WebSocket state
        self._fill_callbacks: dict[str, Callable] = {}  # order_id -> callback function
        self._order_cache: dict[str, dict] = {}  # order_id -> latest order message
        self._position_cache: dict[str, dict] = {}  # symbol -> latest raw position message

        # Authoritative fill prices, volume-weighted across partial executions.
        # Sourced from trade events, which carry the real traded price.
        self._fill_prices: dict[str, float] = {}  # order_id -> avg fill price
        self._fill_qtys: dict[str, int] = {}  # order_id -> cumulative filled qty

        # position_cache is written from the SDK's socket thread and read from the
        # event loop and from shortcircuit.state.reconciliation — guard it.
        self._position_cache_lock = threading.Lock()
        self._position_cache_last_event: float = 0.0

        # WS quote cache, read by the scanner pre-filter.
        self._quote_cache: dict[str, CacheEntry] = {}
        self._quote_cache_lock = threading.Lock()
        self._ws_subscribed_symbols: list[str] = []

        # Leverage cache (symbol -> leverage_float)
        self._leverage_cache: dict[str, float] = {}
        self._leverage_cache_lock = threading.Lock()
        self._low_leverage_blacklist: set[str] = set()  # Session-long block
        self._ws_subscribed_symbols_set: set[str] = set()

        # Cache reliability state machine.
        self._cache_state: str = "UNINITIALIZED"  # UNINITIALIZED | PRIMING | READY | DEGRADED
        self._cache_ready_event = threading.Event()  # Set when readiness threshold first crossed
        self._subscribed_count: int = 0
        self._ws_subscribed_symbols: list[str] = []
        self._ws_subscribed_symbols_set: set[str] = set()

        # Same state machine, backed by the BrokerHealthState enum. The string
        # form above is kept as a legacy compatibility property.
        self._health_state: BrokerHealthState = BrokerHealthState.UNINITIALIZED
        self._cache_state: str = (
            "UNINITIALIZED"  # legacy compat property (derived from _health_state)
        )
        self._cache_ready_event = threading.Event()  # Set when readiness threshold first crossed
        self._subscribed_count: int = 0
        self._prime_start_ts: float = 0.0
        self._health_monitor_thread: threading.Thread | None = None
        self._health_monitor_running: bool = False
        self._reprime_requested: bool = False
        self._last_reprime_time: float = 0.0
        self._consecutive_reprime_failures: int = 0
        self._sub_ack = threading.Event()  # blocks until Fyers confirms subscription
        self._ws_cache_stop = False

        # Health is tracked per socket: the two reconnect independently.
        self._data_ws_health: WSHealth = WSHealth()
        self._order_ws_health: WSHealth = WSHealth()

        # Session-level recovery telemetry
        self._total_reprime_attempts: int = 0
        self._total_reconnect_attempts: int = 0
        self._capital_sync_timeout_count: int = 0
        self._reconcile_timeout_count: int = 0
        self._session_degraded_seconds: float = 0.0
        self._degraded_state_entered_at: float = 0.0  # epoch when last entered a non-READY state
        self._last_cached_funds: dict = {}  # last known good funds
        self._health_state_entered_at: float = time.time()

        # Telegram hook for WS cache alerts
        # Set via broker.set_telegram(bot) from shortcircuit.runtime.supervisor.py after both are constructed
        self._telegram_bot = None

        # Severe-degraded tracking (fresh < 5% for > 30s triggers recovery)
        self._severe_degraded_since: float = 0.0  # epoch when fresh% first dropped below 5%
        self._last_degraded_telegram_alert: float = 0.0  # throttle Telegram spam
        self._degraded_scan_count: int = 0  # incremented by scanner for banner log

        # Background tasks
        self.tasks = []

    # State transition helper
    def _transition_health_state(self, new_state: BrokerHealthState, reason: str = ""):
        """
        Single canonical method for all health state transitions.
        Logs every transition exactly once with timing context.
        """
        old_state = self._health_state
        if old_state == new_state:
            return
        now = time.time()
        elapsed = now - self._health_state_entered_at
        self._health_state = new_state
        self._cache_state = new_state.value  # keep legacy string compat
        self._health_state_entered_at = now

        # Accumulate degraded time when leaving a non-READY state
        non_ready = {
            BrokerHealthState.DEGRADED,
            BrokerHealthState.CRITICAL,
            BrokerHealthState.SEVERE_DEGRADED,
            BrokerHealthState.REPRIME_PENDING,
            BrokerHealthState.FULL_RECONNECT_PENDING,
            BrokerHealthState.HYBRID_REST_MODE,
        }
        if old_state in non_ready:
            self._session_degraded_seconds += elapsed

        reason_str = f" | reason={reason}" if reason else ""
        logger.info(
            f"[WS] STATE TRANSITION: {old_state.value} → {new_state.value} "
            f"(elapsed={elapsed:.1f}s{reason_str})"
        )

    def _classify_health(self, fresh_pct: float) -> BrokerHealthState:
        """Deterministic health classification from fresh WS percentage alone."""
        if fresh_pct >= 0.85:
            return BrokerHealthState.READY
        elif fresh_pct >= 0.50:
            return BrokerHealthState.DEGRADED
        elif fresh_pct >= 0.05:
            return BrokerHealthState.CRITICAL
        else:
            return BrokerHealthState.SEVERE_DEGRADED

    def get_health_state(self) -> BrokerHealthState:
        """Returns the current formal health state."""
        return self._health_state

    def get_health_report(self) -> dict:
        """
        Phase PRD-WS: Returns complete broker health telemetry.
        Used by /health Telegram command and internal diagnostics.
        """
        snap = self.cache_health_snapshot()
        now = time.time()
        total = max(snap["total"], 1)
        fresh_pct = snap["fresh"] / total
        time_in_state = now - self._health_state_entered_at
        return {
            # State
            "health_state": self._health_state.value,
            "time_in_state_secs": round(time_in_state, 1),
            # Data socket
            "data_ws_connected": self._data_ws_health.connected,
            "data_ws_reconnects": self._data_ws_health.reconnect_count,
            "data_ws_last_event_age": round(now - self._data_ws_health.last_event_time, 1)
            if self._data_ws_health.last_event_time
            else None,
            # Order socket
            "order_ws_connected": self._order_ws_health.connected,
            "order_ws_reconnects": self._order_ws_health.reconnect_count,
            # Cache
            "fresh_count": snap["fresh"],
            "known_count": snap["populated"],
            "seeded_count": snap["seeded"],
            "stale_count": snap["stale"],
            "missing_count": snap["missing"],
            "total_subscribed": snap["total"],
            "fresh_pct": round(fresh_pct * 100, 1),
            "age_p50": snap["age_p50"],
            "age_p95": snap["age_p95"],
            "age_p99": snap["age_p99"],
            # Recovery counters
            "total_reprime_attempts": self._total_reprime_attempts,
            "total_reconnect_attempts": self._total_reconnect_attempts,
            "consecutive_reprime_fails": self._consecutive_reprime_failures,
            # Session metrics
            "session_degraded_secs": round(self._session_degraded_seconds, 1),
            "capital_sync_timeouts": self._capital_sync_timeout_count,
            "reconcile_timeouts": self._reconcile_timeout_count,
            # Order pipeline — proves the fill path is actually live
            "positions_cached": len(self.position_cache),
            "position_event_age": (
                round(now - self._position_cache_last_event, 1)
                if self._position_cache_last_event
                else None
            ),
            "orders_tracked": len(self.order_status_cache),
            "fills_recorded": len(self._fill_prices),
            # REST budget
            "rate_limit": rest_limiter.snapshot(),
        }

    def get_local_candles(self, symbol: str, n: int = 100) -> list[Candle]:
        """Exposes aggregated local candles to the Analyzer."""
        return self.aggregator.get_candles(symbol, n)

    async def initialize(self):
        logger.info("Initializing Fyers Broker Interface...")
        self._loop = asyncio.get_running_loop()
        self._transition_health_state(BrokerHealthState.CONNECTING, "broker startup")

        # Step 1: REST API — FATAL if fails
        try:
            profile = self.rest_client.get_profile()
            if profile.get("s") == "ok":
                name = profile["data"].get("name", "Unknown")
                logger.info(f"REST API connected: {name}")
            else:
                raise ConnectionError(f"REST API auth failed: {profile}")
        except Exception as e:
            raise ConnectionError(f"Broker REST init failed: {e}")

        # Step 2: Init WebSocket objects — NON-FATAL
        await self._init_order_websocket()
        await self._init_data_websocket()

        # Step 3: Connect WebSockets in background threads — NON-FATAL
        await self._connect_websockets()

        # Step 4: Start background maintenance tasks
        self.tasks.append(asyncio.create_task(self._websocket_keepalive()))
        self.tasks.append(asyncio.create_task(self._cache_cleanup()))

        logger.info("✅ Broker interface initialized successfully")

    async def _init_data_websocket(self):
        """Initialize Fyers v3 Data WebSocket."""
        if not _WS_AVAILABLE or _data_ws_module is None:
            logger.warning("Data WebSocket skipped: module not available")
            return

        try:
            log_dir = Path("logs/fyers_data_ws")
            log_dir.mkdir(parents=True, exist_ok=True)

            # Fyers v3 requires combined token format
            full_token = f"{self.client_id}:{self.access_token}"

            self.data_ws = _data_ws_module.FyersDataSocket(
                access_token=full_token,
                log_path=str(log_dir) + os.sep,
                litemode=False,  # Full data
                write_to_file=False,  # We handle logging
                reconnect=True,  # Auto-reconnect
                on_connect=self._on_data_ws_connect,
                on_close=self._on_data_ws_close,
                on_error=self._on_data_ws_error,
                on_message=self._handle_tick,
            )
            logger.info("✅ Data WebSocket initialized (pending connect)")
        except Exception as e:
            logger.error(f"Data WebSocket init failed: {e}")
            self.data_ws = None

    async def _init_order_websocket(self):
        """Initialize Fyers v3 Order WebSocket."""
        if not _WS_AVAILABLE or _order_ws_module is None:
            logger.warning("Order WebSocket skipped: module not available")
            return

        try:
            log_dir = Path("logs/fyers_order_ws")
            log_dir.mkdir(parents=True, exist_ok=True)

            full_token = f"{self.client_id}:{self.access_token}"

            self.order_ws = _order_ws_module.FyersOrderSocket(
                access_token=full_token,
                write_to_file=False,
                log_path=str(log_dir) + os.sep,
                reconnect=True,
                on_connect=self._on_order_ws_connect,
                on_close=self._on_order_ws_close,
                on_error=self._on_order_ws_error,
                on_orders=self._handle_order_update,
                on_positions=self._handle_position_update,
                on_trades=self._handle_trade_update,
                on_general=self._handle_general_update,
            )
            logger.info("✅ Order WebSocket initialized (pending connect)")
        except Exception as e:
            logger.error(f"Order WebSocket init failed: {e}")
            self.order_ws = None

    def _start_data_ws(self):
        """Start Data WebSocket connection (Blocking - Run in Thread)."""
        if self.data_ws:
            try:
                self.data_ws.connect()
            except Exception as e:
                logger.error(f"Data WS connection error: {e}")
                self.ws_connected = False

    def _start_order_ws(self):
        """Start Order WebSocket connection (Blocking - Run in Thread)."""
        if self.order_ws:
            try:
                self.order_ws.connect()
            except Exception as e:
                logger.error(f"Order WS connection error: {e}")

    async def _connect_websockets(self):
        """Launch both WebSocket connections in background thread executors."""
        loop = asyncio.get_event_loop()

        if self.data_ws:
            loop.run_in_executor(None, self._start_data_ws)
            logger.info("Data WebSocket connecting (background thread)...")

        if self.order_ws:
            loop.run_in_executor(None, self._start_order_ws)
            logger.info("Order WebSocket connecting (background thread)...")

    def _on_data_ws_connect(self):
        """Called by Fyers SDK when Data WebSocket opens."""
        logger.info("✅ Data WebSocket connected")
        self.ws_connected = True
        self.data_ws_connected = True
        self._data_ws_health.connected = True
        self._data_ws_health.last_event_time = time.time()

        # Subscribe to all watched symbols immediately on connect
        if self.subscribed_symbols:
            symbols = list(self.subscribed_symbols)
            # FyersDataSocket subscribe take symbols argument
            self.data_ws.subscribe(symbols=symbols, data_type="SymbolUpdate")
            logger.info(f"Subscribed to {len(symbols)} symbols")

    def _on_order_ws_connect(self):
        """Called by Fyers SDK when Order WebSocket opens."""
        logger.info("✅ Order WebSocket connected")
        self.order_ws_connected = True
        self._order_ws_health.connected = True
        self._order_ws_health.last_event_time = time.time()
        # Subscribe to all order/position events
        if self.order_ws:
            self.order_ws.subscribe(data_type="OnOrders,OnTrades,OnPositions,OnGeneral")
        logger.info("Order WebSocket subscribed to all events")

    def _on_data_ws_close(self, message):
        logger.warning(f"Data WebSocket closed: {message}")
        self.ws_connected = False
        self.data_ws_connected = False
        self._data_ws_health.connected = False
        self._data_ws_health.last_close_reason = str(message)[:200]
        self._data_ws_health.reconnect_count += 1

    def _on_order_ws_close(self, message):
        logger.warning(f"Order WebSocket closed: {message}")
        self.order_ws_connected = False
        self._order_ws_health.connected = False
        self._order_ws_health.last_close_reason = str(message)[:200]
        self._order_ws_health.reconnect_count += 1

    def _on_data_ws_error(self, message):
        logger.error(f"Data WebSocket error: {message}")
        self._data_ws_health.last_error = str(message)[:200]

    def _on_order_ws_error(self, message):
        logger.error(f"Order WebSocket error: {message}")
        self._order_ws_health.last_error = str(message)[:200]

    def _handle_general_update(self, message: dict):
        """
        Called by Order WebSocket for general/system messages.
        Examples: connection status, session expiry warnings.
        """
        try:
            if not message:
                return
            logger.debug(f"ℹ️ General WS Update: {message}")

            # Check for session expiry warning from Fyers
            msg_type = message.get("type") or message.get("s", "")
            if "expire" in str(msg_type).lower() or "logout" in str(msg_type).lower():
                logger.warning(
                    "⚠️ Fyers session expiry warning received. "
                    "Token may need refresh after market close."
                )

        except Exception as e:
            logger.error(f"_handle_general_update error: {e}")

    def _handle_tick(self, message: dict):
        """
        Handle market tick from WebSocket.
        """
        try:
            # Update scanner quote cache
            # Detect subscription ACK from Fyers
            msg_type = message.get("type")
            if msg_type == "sub" and message.get("code") == 200:
                self._sub_ack.set()
                logger.info("[WS Cache] ✅ Subscription ACK received from Fyers server")
                return

            # Permanent first-tick diagnostic log
            if not hasattr(self, "_first_tick_logged"):
                if msg_type not in ("cn", "ful", "op", "sf", "os"):
                    logger.info(f"[WS Cache] ✅ FIRST DATA TICK: {str(message)[:200]}")
                    self._first_tick_logged = True
            symbol = message.get("symbol") or message.get("n")
            if (
                symbol
                and hasattr(self, "_ws_subscribed_symbols_set")
                and symbol in self._ws_subscribed_symbols_set
            ):
                with self._quote_cache_lock:
                    prev_entry = self._quote_cache.get(symbol)

                    # Merge incoming tick data with prev_entry fallbacks
                    # Coerce None → 0 to prevent NoneType comparison crashes on pre-market ticks
                    ltp = message.get("ltp", prev_entry.last_price if prev_entry else 0) or 0
                    volume = (
                        message.get(
                            "vol_traded_today",
                            message.get("v", prev_entry.volume if prev_entry else 0),
                        )
                        or 0
                    )
                    oi = message.get("oi", prev_entry.oi if prev_entry else 0) or 0
                    bid = message.get("bid", prev_entry.bid if prev_entry else 0) or 0
                    ask = message.get("ask", prev_entry.ask if prev_entry else 0) or 0
                    open_price = (
                        message.get(
                            "open_price",
                            message.get("o", prev_entry.open_price if prev_entry else 0),
                        )
                        or 0
                    )
                    high_price = (
                        message.get(
                            "high_price",
                            message.get("h", prev_entry.high_price if prev_entry else 0),
                        )
                        or 0
                    )
                    prev_close = (
                        message.get(
                            "prev_close_price",
                            message.get("pc", prev_entry.prev_close if prev_entry else 0),
                        )
                        or 0
                    )
                    ch_oc = (
                        message.get(
                            "ch_oc", message.get("chp", prev_entry.ch_oc if prev_entry else 0)
                        )
                        or 0
                    )

                    # Re-calculate ch_oc manually if it evaluates to 0 but prev_close > 0 and ltp > 0
                    if (
                        message.get("ch_oc", message.get("chp", 0)) == 0
                        and prev_close > 0
                        and ltp > 0
                    ):
                        ch_oc = ((ltp - prev_close) / prev_close) * 100

                    tick_count = 1
                    if prev_entry and prev_entry.source == CacheEntrySource.WS_TICK:
                        tick_count = prev_entry.tick_count + 1

                    self._quote_cache[symbol] = CacheEntry(
                        last_price=ltp,
                        volume=volume,
                        ch_oc=ch_oc,
                        oi=oi,
                        bid=bid,
                        ask=ask,
                        open_price=open_price,
                        high_price=high_price,
                        prev_close=prev_close,
                        last_time=time.time(),
                        source=CacheEntrySource.WS_TICK,
                        tick_count=tick_count,
                    )
                    # Advance PRIMING → READY state machine on each tick
                    self._check_cache_readiness_internal()

            # Fyers DataSocket returns dict structure
            tick = TickData(message)

            # Store in deque (last 100 ticks = ~30 seconds)
            if tick.symbol not in self.tick_cache:
                self.tick_cache[tick.symbol] = deque(maxlen=100)

            self.tick_cache[tick.symbol].append(tick)

            # Update Local Candle Engine
            if getattr(config, "P82_LOCAL_CANDLES_ENABLED", False):
                self.aggregator.update(tick)

            # Call registered callbacks
            for callback in self.on_tick_callbacks:
                try:
                    callback(tick)
                except Exception as e:
                    logger.error(f"Tick callback error: {e}")

        except Exception as e:
            logger.error(f"Error handling tick: {e}")

    # Order WebSocket callbacks
    # All called by FyersOrderSocket when events arrive

    def _signal_order_waiters(self, order_id: str) -> None:
        """
        Wake any wait_for_fill() coroutine watching this order.

        Order-socket callbacks run on the SDK's own thread, so the asyncio.Event
        must be set via call_soon_threadsafe. Setting it directly from this thread
        is not thread-safe and can be missed entirely by the waiting loop.
        """
        event = self.order_fill_events.get(order_id)
        if event is None:
            return
        loop = getattr(self, "_loop", None)
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(event.set)
                return
            except RuntimeError:
                pass
        event.set()  # fallback: same-thread or loop unavailable

    def _handle_order_update(self, message: dict):
        """
        Called by the Order WebSocket on every order status change.

        Payload arrives wrapped as {'s': 'ok', 'orders': {...}} — see
        unwrap_ws_payload for why reading the envelope's top level silently failed.
        """
        try:
            order = unwrap_ws_payload(message, "orders")
            if not order:
                logger.debug("Order update with no usable payload: %s", message)
                return

            order_id = str(
                order.get("id") or order.get("orderId") or order.get("order_id") or ""
            ).strip()
            if not order_id:
                logger.debug("Order update with no ID: %s", order)
                return

            status = FyersOrderStatus.coerce(order.get("status"))
            filled_qty = order.get("filledQty", 0) or 0
            fill_price = order.get("tradedPrice", 0) or 0.0
            remaining = order.get("remainingQuantity", 0) or 0

            # Publish to the cache BEFORE waking waiters, so a waiter that runs
            # immediately observes this update rather than the previous one.
            update = OrderUpdate({**order, "id": order_id, "status": status})
            self.order_status_cache[order_id] = update
            self._order_cache[order_id] = order

            # A trade event may have already reported the true average fill price;
            # never regress it to 0 just because this status frame omitted it.
            if not fill_price:
                known = self._fill_prices.get(order_id)
                if known:
                    update.avg_price = known

            self._signal_order_waiters(order_id)

            # Legacy per-order callbacks
            cb = self._fill_callbacks.get(order_id)
            if cb is not None:
                try:
                    cb(order)
                except Exception as cb_err:
                    logger.error("Fill callback error for %s: %s", order_id, cb_err)

            for callback in self.on_order_update_callbacks:
                try:
                    callback(update)
                except Exception as e:
                    logger.error("on_order_update callback error: %s", e)

            label = status.name if status else f"UNKNOWN({order.get('status')})"
            mark = {"FILLED": " ✅", "REJECTED": " ❌", "CANCELLED": " ⛔"}.get(label, "")
            logger.info(
                "Order %s: %s%s | %s | filled=%s remaining=%s price=₹%s%s",
                order_id,
                label,
                mark,
                order.get("symbol", "?"),
                filled_qty,
                remaining,
                fill_price,
                f" | {order.get('message')}" if order.get("message") else "",
            )

        except Exception as e:
            logger.error("_handle_order_update error: %s | message: %s", e, message)

    def _handle_position_update(self, message: dict):
        """
        Called by the Order WebSocket when a position changes.

        Writes into self.position_cache — the cache that get_all_positions() and
        ReconciliationEngine._read_broker_cache() actually read. Previously this
        wrote to a different, unread dict, so the WS position pipeline was inert
        and every consumer silently fell back to REST polling.
        """
        try:
            pos = unwrap_ws_payload(message, "positions")
            if not pos:
                return

            symbol = pos.get("symbol")
            if not symbol:
                return

            update = PositionUpdate(pos)
            with self._position_cache_lock:
                if update.net_qty == 0:
                    # Flat: drop it so stale non-zero state can never be re-read.
                    self.position_cache.pop(symbol, None)
                else:
                    self.position_cache[symbol] = update
                self._position_cache[symbol] = {
                    "data": pos,
                    "timestamp": datetime.now(UTC),
                }
                self._position_cache_last_event = time.time()

            logger.debug(
                "📊 Position: %s netQty=%s avg=%s realised=%s",
                symbol,
                update.net_qty,
                update.avg_price,
                update.realized_pnl,
            )

            for callback in self.on_position_update_callbacks:
                try:
                    callback(update)
                except Exception as e:
                    logger.error("on_position_update callback error: %s", e)

        except Exception as e:
            logger.error("_handle_position_update error: %s", e)

    def _handle_trade_update(self, message: dict):
        """
        Called by the Order WebSocket on each execution.

        Trades carry the authoritative traded price. Note the trade mapper emits
        `orderNumber` (not `id`) for the parent order — correlating on `id` here
        would silently never match.
        """
        try:
            trade = unwrap_ws_payload(message, "trades")
            if not trade:
                return

            order_id = str(trade.get("orderNumber") or trade.get("id") or "").strip()
            price = trade.get("tradePrice", 0) or 0.0
            qty = trade.get("tradedQty", 0) or 0
            symbol = trade.get("symbol", "?")
            side = "BUY" if trade.get("side") == 1 else "SELL"

            if order_id and price:
                # Volume-weight across partial fills so the recorded entry price is
                # the real average, not just the last slice.
                prev_px = self._fill_prices.get(order_id, 0.0)
                prev_qty = self._fill_qtys.get(order_id, 0)
                total_qty = prev_qty + qty
                if total_qty > 0:
                    self._fill_prices[order_id] = ((prev_px * prev_qty) + (price * qty)) / total_qty
                    self._fill_qtys[order_id] = total_qty

                cached = self.order_status_cache.get(order_id)
                if cached is not None:
                    cached.avg_price = self._fill_prices[order_id]

                self._signal_order_waiters(order_id)

            logger.info(
                "💹 TRADE | %s %s %s @ ₹%s | order=%s trade=%s",
                side,
                qty,
                symbol,
                price,
                order_id,
                trade.get("tradeNumber"),
            )

        except Exception as e:
            logger.error("_handle_trade_update error: %s", e)

    async def _websocket_keepalive(self):
        """
        Watchdog for the ORDER socket.

        The data socket has its own health-monitor thread; the order socket had no
        supervision at all, so a silent drop meant fills stopped arriving with no
        alarm — indistinguishable from an idle market. We detect staleness and
        rebuild the socket.
        """
        CHECK_INTERVAL = 30
        SILENCE_LIMIT = 180.0  # no event AND disconnected for this long → rebuild

        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL)

                if not is_market_hours_ist():
                    continue

                health = self._order_ws_health
                now = time.time()
                last = health.last_event_time or self._health_state_entered_at
                silence = now - last

                if health.connected:
                    continue

                if silence < SILENCE_LIMIT:
                    logger.warning(
                        "[ORDER-WS] Disconnected %.0fs (limit %.0fs) — awaiting SDK auto-reconnect.",
                        silence,
                        SILENCE_LIMIT,
                    )
                    continue

                logger.critical(
                    "[ORDER-WS] Down for %.0fs with no events — rebuilding socket. "
                    "Fills cannot be confirmed while this socket is dead.",
                    silence,
                )
                self._send_telegram_alert_async(
                    "🚨 *ORDER SOCKET DOWN*\n\n"
                    f"No order events for {silence:.0f}s. Rebuilding.\n"
                    "_Fill confirmation is degraded to REST until this recovers._"
                )
                try:
                    await self._init_order_websocket()
                    if self.order_ws:
                        await asyncio.get_event_loop().run_in_executor(None, self._start_order_ws)
                        self._order_ws_health.reconnect_count += 1
                        logger.info("[ORDER-WS] Reconnect dispatched.")
                except Exception as e:
                    logger.critical("[ORDER-WS] Rebuild failed: %s", e)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("[ORDER-WS] Keepalive error: %s", e)

    async def _cache_cleanup(self):
        """Background task to evict stale cache entries and bound memory growth."""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            try:
                now = datetime.now(UTC)

                for symbol in list(self.tick_cache.keys()):
                    ticks = self.tick_cache[symbol]
                    if ticks:
                        latest = ticks[-1].timestamp
                        if (now - latest).total_seconds() > 3600:
                            del self.tick_cache[symbol]

                expired_orders = []
                for order_id in list(self.order_status_cache.keys()):
                    update = self.order_status_cache[order_id]
                    if (now - update.timestamp).total_seconds() > 3600:
                        # Never evict an order someone is actively waiting on.
                        if order_id in self.order_fill_events:
                            continue
                        expired_orders.append(order_id)

                for order_id in expired_orders:
                    self.order_status_cache.pop(order_id, None)
                    self._order_cache.pop(order_id, None)
                    self._fill_prices.pop(order_id, None)
                    self._fill_qtys.pop(order_id, None)
                    self._fill_callbacks.pop(order_id, None)

                # Drop position entries that went flat and were never re-touched.
                with self._position_cache_lock:
                    for symbol in list(self.position_cache.keys()):
                        p = self.position_cache[symbol]
                        if p.net_qty == 0 or (now - p.timestamp).total_seconds() > 3600:
                            self.position_cache.pop(symbol, None)
                            self._position_cache.pop(symbol, None)

                if expired_orders:
                    logger.debug("[CACHE] Evicted %d completed orders.", len(expired_orders))
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")

    def subscribe_scanner_universe(self, symbols: list[str]) -> None:
        """
        Subscribe all scanner symbols to dataws in symbolUpdate mode.
        Called once at startup after dataws is connected.
        Splits into batches of 50 — Fyers dataws limit per subscribe call.
        Resets the cache state machine to PRIMING and starts the health monitor.
        """
        self._ws_subscribed_symbols = symbols
        self._ws_subscribed_symbols_set = set(symbols)
        self._subscribed_count = len(symbols)
        self._transition_health_state(BrokerHealthState.PRIMING, "subscribe_scanner_universe")
        self._cache_ready_event.clear()
        self._prime_start_ts = time.time()
        self._reprime_requested = False
        self._sub_ack.clear()  # reset ACK before subscribing

        # 3s post-connect delay — Fyers needs auth handshake to complete server-side
        logger.info("[WS Cache] Waiting 3s post-connect before subscribing...")
        time.sleep(3)

        batch_size = 50
        total = 0
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            try:
                if self.data_ws:
                    # Pace WS subscriptions to prevent Fyers server drops on heavy volume days
                    time.sleep(0.5)
                    self.data_ws.subscribe(symbols=batch, data_type="SymbolUpdate")
                total += len(batch)
            except Exception as e:
                logger.error(f"[WS Cache] Subscribe batch {i // batch_size} failed: {e}")
        logger.info(
            f"[WS Cache] Subscribed {total}/{len(symbols)} symbols to dataws SymbolUpdate — state=PRIMING"
        )

        # Wait for subscription ACK (10s timeout)
        if not self._sub_ack.wait(timeout=10.0):
            logger.critical(
                "[WS Cache] ❌ No subscription ACK from Fyers after 10s — "
                "connection may be dead or data_type wrong"
            )
        else:
            logger.info("[WS Cache] ✅ Subscription confirmed by Fyers server")

        # Evaluate readiness immediately (supports REST-seeded startup path).
        with self._quote_cache_lock:
            self._check_cache_readiness_internal()

        # Start health monitor thread — check actual liveness, not just the flag
        thread_dead = (
            self._health_monitor_thread is not None and not self._health_monitor_thread.is_alive()
        )
        if not self._health_monitor_running or thread_dead:
            self._health_monitor_running = True
            self._health_monitor_thread = threading.Thread(
                target=self._run_cache_health_monitor, name="WSCacheHealthMonitor", daemon=True
            )
            self._health_monitor_thread.start()
            logger.info("[WS Cache] Health monitor thread started")

    def get_quote_cache_snapshot(self) -> dict[str, dict]:
        """
        Returns a shallow copy of the current quote cache.
        Called by scanner.scan_market() — thread-safe.
        """
        with self._quote_cache_lock:
            return {
                symbol: {
                    "ltp": entry.last_price,
                    "volume": entry.volume,
                    "ch_oc": entry.ch_oc,
                    "oi": entry.oi,
                    "bid": entry.bid,
                    "ask": entry.ask,
                    "open": entry.open_price,
                    "high": entry.high_price,
                    "pc": entry.prev_close,
                    "ts": entry.last_time,
                    "source": entry.source.value,
                    "tick_count": entry.tick_count,
                }
                for symbol, entry in self._quote_cache.items()
            }

    def seed_from_rest(self, symbols: list[str]) -> int:
        """
        Seed quote cache from REST snapshot at startup.
        Seeded entries are "known" but not "fresh" for WS readiness.
        """
        if not symbols:
            return 0

        seeded = 0
        batch_size = 50
        now_ts = time.time()
        logger.info("[WS Cache] Seeding %s symbols from REST snapshot...", len(symbols))

        with self._quote_cache_lock:
            if self._subscribed_count == 0:
                self._subscribed_count = len(symbols)

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            try:
                # Acquire global rate limiter token before each REST call
                rest_limiter.acquire()
                response = self.rest_client.quotes(data={"symbols": ",".join(batch)})
            except Exception as e:
                logger.warning("[WS Cache] REST seed batch %s failed: %s", i // batch_size, e)
                continue

            if response.get("s") != "ok":
                continue

            for quote in response.get("d", []):
                symbol = quote.get("n")
                qv = quote.get("v", {})
                ltp = qv.get("lp", 0)
                if not symbol or not ltp:
                    continue

                with self._quote_cache_lock:
                    existing = self._quote_cache.get(symbol)
                    # Never override live WS ticks with REST seed.
                    if existing and existing.source == CacheEntrySource.WS_TICK:
                        continue
                    self._quote_cache[symbol] = CacheEntry(
                        last_price=ltp,
                        volume=qv.get("v", qv.get("volume", 0)),
                        ch_oc=qv.get("chp", qv.get("ch_oc", 0)),
                        oi=qv.get("oi", 0),
                        bid=qv.get("bid", 0),
                        ask=qv.get("ask", 0),
                        open_price=qv.get("o", qv.get("open_price", 0)),
                        high_price=qv.get("h", qv.get("high_price", 0)),
                        prev_close=qv.get("pc", qv.get("prev_close_price", 0)),
                        last_time=now_ts,
                        source=CacheEntrySource.REST_SEED,
                        tick_count=0,
                    )
                seeded += 1

        logger.info("[WS Cache] ✅ REST seed complete: %s/%s symbols seeded", seeded, len(symbols))
        return seeded

    def _is_fresh_entry(self, entry: CacheEntry, freshness_ttl: float, now_ts: float) -> bool:
        return (
            entry.source == CacheEntrySource.WS_TICK and (now_ts - entry.last_time) < freshness_ttl
        )

    def is_known(self, symbol: str) -> bool:
        with self._quote_cache_lock:
            return symbol in self._quote_cache

    # Cache Readiness & Health

    def _get_readiness_threshold(self) -> float:
        """Returns readiness threshold based on market session timing."""
        try:
            from shortcircuit import config

            mins_open = config.minutes_since_market_open()
            if mins_open < 30:
                return 0.85  # Opening: 85% (strict)
            else:
                return 0.80  # Mid-market/late: 80%
        except Exception:
            return 0.85

    def _check_cache_readiness_internal(self):
        """
        Called on every tick during PRIMING. Sets the readiness event
        and transitions state to READY once threshold is crossed.
        Must be called under _quote_cache_lock.
        """
        if (
            self._health_state not in (BrokerHealthState.PRIMING, BrokerHealthState.REPRIME_PENDING)
            or self._subscribed_count == 0
        ):
            return

        import shortcircuit.config as _cfg

        freshness_ttl = _cfg.WS_TICK_FRESHNESS_TTL_SECONDS
        now = time.time()
        fresh_count = sum(
            1
            for entry in self._quote_cache.values()
            if self._is_fresh_entry(entry, freshness_ttl, now)
        )
        known_count = len(self._quote_cache)
        fresh_pct = fresh_count / self._subscribed_count
        known_pct = known_count / self._subscribed_count
        threshold = self._get_readiness_threshold()

        if fresh_pct >= threshold or known_pct >= 0.90:
            self._transition_health_state(
                BrokerHealthState.READY, f"fresh={fresh_pct:.1%} known={known_pct:.1%}"
            )
            self._cache_ready_event.set()
            elapsed = now - self._prime_start_ts
            reason = (
                f"fresh {fresh_pct:.1%} >= {threshold:.0%}"
                if fresh_pct >= threshold
                else f"known {known_pct:.1%} >= 90%"
            )
            logger.info(
                f"[WS Cache] CACHE READY: {fresh_count}/{self._subscribed_count} symbols fresh "
                f"| known={known_count}/{self._subscribed_count} ({known_pct:.1%}) "
                f"| reason={reason} after {elapsed:.1f}s"
            )

    def is_cache_ready(self) -> bool:
        """Returns True if cache is in READY or RECOVERED state (safe to scan)."""
        return self._health_state in (
            BrokerHealthState.READY,
            BrokerHealthState.RECOVERED,
            BrokerHealthState.DEGRADED,
            BrokerHealthState.CRITICAL,
            BrokerHealthState.HYBRID_REST_MODE,
        )

    def wait_for_cache_ready(self, timeout_sec: float = 45.0) -> bool:
        """
        Blocks caller until cache is READY or timeout expires.
        Returns True if ready, False on timeout.
        Used by startup gate in main.py via asyncio.to_thread().
        """
        return self._cache_ready_event.wait(timeout=timeout_sec)

    def set_telegram(self, telegram_bot) -> None:
        """
        Wire Telegram bot for WS cache degradation alerts.
        Called from shortcircuit.runtime.supervisor after both broker and bot are initialized:
            broker.set_telegram(telegram_bot)
        """
        self._telegram_bot = telegram_bot
        logger.info("[WS Cache] Telegram bot wired for cache degradation alerts.")

    # Health states in which the WS feed cannot be trusted for scanning.
    _SEVERE_STATES = (
        BrokerHealthState.SEVERE_DEGRADED,
        BrokerHealthState.REPRIME_PENDING,
        BrokerHealthState.FULL_RECONNECT_PENDING,
        BrokerHealthState.HYBRID_REST_MODE,
        BrokerHealthState.UNRECOVERABLE,
    )

    def is_cache_severely_degraded(self) -> bool:
        """
        True when the feed has been in a severe state for more than 30 seconds.

        This method was previously defined twice. The first definition checked the
        health state but read `time.time() - self._severe_degraded_since` without
        guarding the 0.0 sentinel — so it returned True the instant any severe state
        was entered. The second (which silently won) checked the timestamp but
        ignored health state entirely. This merges both correctly.

        Called by scanner.py and focus_engine.py for the DEGRADED scan banner.
        """
        if self._severe_degraded_since <= 0:
            return False
        if self._health_state not in self._SEVERE_STATES:
            return False
        return (time.time() - self._severe_degraded_since) >= 30

    def increment_degraded_scan_count(self) -> int:
        """
        Called by scanner on each scan while severely degraded.
        Returns current count for banner modulo check.
        """
        self._degraded_scan_count += 1
        return self._degraded_scan_count

    def reset_degraded_scan_count(self) -> None:
        self._degraded_scan_count = 0

    def cache_health_snapshot(self) -> dict:
        """Returns current cache health metrics dict."""
        import shortcircuit.config as _cfg

        freshness_ttl = _cfg.WS_TICK_FRESHNESS_TTL_SECONDS
        with self._quote_cache_lock:
            now = time.time()
            ages = [(now - entry.last_time) for entry in self._quote_cache.values()]
            fresh = sum(
                1
                for entry in self._quote_cache.values()
                if self._is_fresh_entry(entry, freshness_ttl, now)
            )
            seeded = sum(
                1
                for entry in self._quote_cache.values()
                if entry.source == CacheEntrySource.REST_SEED
            )
            populated = len(self._quote_cache)
            total = self._subscribed_count
            sorted_ages = sorted(ages) if ages else [0]

        return {
            "total": total,
            "populated": populated,
            "fresh": fresh,
            "stale": max(0, populated - fresh - seeded),
            "seeded": seeded,
            "missing": max(0, total - populated),
            "age_p50": sorted_ages[len(sorted_ages) // 2],
            "age_p95": sorted_ages[int(len(sorted_ages) * 0.95)],
            "age_p99": sorted_ages[int(len(sorted_ages) * 0.99)]
            if len(sorted_ages) >= 100
            else sorted_ages[-1],
            "state": self._cache_state,
        }

    # Freshness validation helper

    def _wait_for_freshness_recovery(self, timeout_secs: float = 60.0) -> bool:
        """
        Phase PRD-WS 2: Polls cache health every 5s until fresh_pct >= threshold.
        Used to validate reprime/reconnect actually restored live data flow.
        Returns True if freshness was restored within timeout, False otherwise.
        """
        import shortcircuit.config as _cfg

        freshness_ttl = _cfg.WS_TICK_FRESHNESS_TTL_SECONDS
        threshold = self._get_readiness_threshold()
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            time.sleep(5)
            with self._quote_cache_lock:
                now = time.time()
                total = max(self._subscribed_count, 1)
                fresh = sum(
                    1
                    for e in self._quote_cache.values()
                    if self._is_fresh_entry(e, freshness_ttl, now)
                )
                fresh_pct = fresh / total
            if fresh_pct >= threshold:
                logger.info(
                    f"[WS] Freshness recovery confirmed: {fresh_pct:.1%} >= {threshold:.0%} threshold"
                )
                return True
        logger.warning(
            f"[WS] Freshness recovery FAILED after {timeout_secs:.0f}s — fresh still below threshold"
        )
        return False

    def _trigger_reprime(self):
        """Unsubscribe all, wait, then re-subscribe. Escalates to full reconnect after 3 failures."""
        if self._reprime_requested:
            logger.warning("[WS Cache] Re-prime already in progress — skipping")
            return

        # 90s throttle between re-primes
        now = time.time()
        if now - self._last_reprime_time < 90:
            logger.warning("[WS Cache] Re-prime throttled — too soon since last attempt")
            return

        self._reprime_requested = True
        self._last_reprime_time = now
        self._consecutive_reprime_failures += 1
        self._total_reprime_attempts += 1
        self._transition_health_state(
            BrokerHealthState.REPRIME_PENDING, f"attempt #{self._consecutive_reprime_failures}"
        )
        self._cache_ready_event.clear()

        logger.warning(f"[WS Cache] Re-prime #{self._consecutive_reprime_failures} triggered")
        self._send_telegram_alert_async(
            f"🔄 *WS Cache REPRIME #{self._consecutive_reprime_failures}*\n"
            f"Auto-recovery attempt starting now."
        )

        # Escalate to full reconnect after 3 consecutive failures
        if self._consecutive_reprime_failures >= 3:
            logger.critical(
                "[WS Cache] 3 consecutive re-prime failures — escalating to FULL RECONNECT"
            )
            self._consecutive_reprime_failures = 0
            self._transition_health_state(
                BrokerHealthState.FULL_RECONNECT_PENDING, "3 reprime failures"
            )
            try:
                self._do_full_ws_reconnect()
            except Exception as e:
                logger.critical(f"[WS Cache] Full reconnect failed: {e}")
                self._transition_health_state(
                    BrokerHealthState.UNRECOVERABLE, f"reconnect exception: {e}"
                )
                self._send_telegram_alert_async(
                    "⛔ *WS Cache UNRECOVERABLE*\n\n3 recovery attempts all failed.\n"
                    "Bot keeps running on REST data. Consider manual restart."
                )
            finally:
                self._reprime_requested = False
            return

        try:
            # Step 1: Unsubscribe all
            if self._ws_subscribed_symbols and self.data_ws:
                try:
                    self.data_ws.unsubscribe(
                        symbols=self._ws_subscribed_symbols, data_type="SymbolUpdate"
                    )
                    logger.info(
                        f"[WS Cache] Unsubscribed {len(self._ws_subscribed_symbols)} symbols"
                    )
                except Exception as unsub_e:
                    logger.warning(f"[WS Cache] Unsubscribe failed (non-fatal): {unsub_e}")

            # Step 2: Wait for server to process unsubscribe
            time.sleep(5)

            # Step 3: Re-subscribe
            if self._ws_subscribed_symbols:
                self.subscribe_scanner_universe(self._ws_subscribed_symbols)

            # Validate freshness was actually restored
            recovered = self._wait_for_freshness_recovery(timeout_secs=60)
            if recovered:
                self._consecutive_reprime_failures = max(0, self._consecutive_reprime_failures - 1)
                self._transition_health_state(BrokerHealthState.RECOVERED, "reprime success")
                self._send_telegram_alert_async(
                    "✅ *WS Cache RECOVERED* (reprime)\nFreshness restored."
                )
            else:
                logger.warning("[WS Cache] Reprime completed but freshness not restored")
        except Exception as e:
            logger.error(f"[WS Cache] Re-prime failed: {e}")
        finally:
            self._reprime_requested = False

    def _do_full_ws_reconnect(self):
        """Nuclear option — full socket teardown + rebuild + freshness validation."""
        self._total_reconnect_attempts += 1
        logger.critical("[WS Cache] ⚡ FULL RECONNECT — tearing down socket")
        self._send_telegram_alert_async(
            f"⚡ *WS FULL RECONNECT* — tearing down and rebuilding socket. Attempt #{self._total_reconnect_attempts}."
        )
        try:
            if self._ws_subscribed_symbols and self.data_ws:
                self.data_ws.unsubscribe(
                    symbols=self._ws_subscribed_symbols, data_type="SymbolUpdate"
                )
            time.sleep(2)
            if self.data_ws:
                self.data_ws.disconnect()
                logger.info("[WS Cache] Socket disconnected")
        except Exception as e:
            logger.error(f"[WS Cache] Disconnect error (continuing): {e}")

        time.sleep(5)  # Let Fyers server fully release the connection

        logger.critical("[WS Cache] ⚡ FULL RECONNECT — rebuilding socket")
        try:
            if self.data_ws:
                self.data_ws.connect()
                time.sleep(2)
            if self._ws_subscribed_symbols:
                self.subscribe_scanner_universe(self._ws_subscribed_symbols)
                # Hard freshness validation after reconnect
                recovered = self._wait_for_freshness_recovery(timeout_secs=90)
                if recovered:
                    logger.info("[WS Cache] ✅ Full reconnect succeeded — freshness validated")
                    self._transition_health_state(
                        BrokerHealthState.RECOVERED, "full reconnect freshness validated"
                    )
                    self._send_telegram_alert_async(
                        "✅ *WS RECONNECT SUCCESS*\nFreshness validated after full reconnect."
                    )
                else:
                    logger.critical(
                        "[WS Cache] Full reconnect did not restore freshness — entering HYBRID REST MODE"
                    )
                    self._transition_health_state(
                        BrokerHealthState.HYBRID_REST_MODE, "reconnect freshness not restored"
                    )
                    self._send_telegram_alert_async(
                        "🛑 *HYBRID REST MODE*\n\nFull WS reconnect failed to restore freshness.\n"
                        "Bot keeps scanning and trading using REST fallback. No positions blocked."
                    )
            else:
                logger.critical("[WS Cache] ❌ No symbols to re-subscribe after reconnect")
        except Exception as e:
            logger.critical(f"[WS Cache] Full reconnect exception: {e}")
            raise

    def _send_telegram_alert_async(self, message: str):
        """Helper: fire-and-forget Telegram alert from a background thread."""
        now = time.time()
        if not self._telegram_bot:
            return
        if now - self._last_degraded_telegram_alert < 120:
            return
        self._last_degraded_telegram_alert = now
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(
                self._telegram_bot.send_util_alert(message), self._loop
            )

    def _run_cache_health_monitor(self):
        """
        Background daemon thread. Runs every 30s.
        PRD-WS: Formal state machine using BrokerHealthState enum.
        Primary degradation signal is fresh_pct from WS ticks only.
        REST-seeded entries never count as fresh.
        """
        while self._health_monitor_running:
            if getattr(self, "_ws_cache_stop", False):
                logger.info("[BROKER] Health monitor stopping on _ws_cache_stop flag.")
                break

            time.sleep(30)
            try:
                snap = self.cache_health_snapshot()
                total = max(snap["total"], 1)
                fresh_pct = snap["fresh"] / total
                known_pct = (snap["fresh"] + snap["stale"] + snap.get("seeded", 0)) / total

                # Classify health
                classified = self._classify_health(fresh_pct)
                current = self._health_state

                # Only transition if not in a recovery/terminal state being managed externally
                recovery_states = {
                    BrokerHealthState.REPRIME_PENDING,
                    BrokerHealthState.FULL_RECONNECT_PENDING,
                    BrokerHealthState.UNRECOVERABLE,
                }

                if current not in recovery_states:
                    if classified == BrokerHealthState.READY:
                        # RECOVERY: returning to healthy
                        if current not in (
                            BrokerHealthState.READY,
                            BrokerHealthState.UNINITIALIZED,
                            BrokerHealthState.CONNECTING,
                            BrokerHealthState.PRIMING,
                        ):
                            elapsed_degraded = (
                                time.time() - self._severe_degraded_since
                                if self._severe_degraded_since
                                else 0
                            )
                            self._transition_health_state(
                                BrokerHealthState.READY, f"fresh={fresh_pct:.1%} recovered"
                            )
                            self._severe_degraded_since = 0.0
                            self._degraded_scan_count = 0
                            self._consecutive_reprime_failures = 0
                            self._send_telegram_alert_async(
                                f"✅ *WS Cache RECOVERED*\n"
                                f"Fresh: {snap['fresh']}/{snap['total']} ({fresh_pct:.1%})\n"
                                f"Was degraded for {elapsed_degraded:.0f}s — returning to TIER 1 WS_CACHE"
                            )
                        else:
                            # Normal READY, no state change needed (already READY)
                            if current != BrokerHealthState.READY:
                                self._transition_health_state(
                                    BrokerHealthState.READY, f"fresh={fresh_pct:.1%}"
                                )
                        self._consecutive_reprime_failures = 0

                    elif classified in (BrokerHealthState.DEGRADED, BrokerHealthState.CRITICAL):
                        if self._severe_degraded_since > 0:
                            self._severe_degraded_since = 0.0  # recovered from severe
                        if current not in (BrokerHealthState.DEGRADED, BrokerHealthState.CRITICAL):
                            self._transition_health_state(classified, f"fresh={fresh_pct:.1%}")

                    else:  # SEVERE_DEGRADED
                        if self._severe_degraded_since == 0.0:
                            self._severe_degraded_since = time.time()
                            self._transition_health_state(
                                BrokerHealthState.SEVERE_DEGRADED, f"fresh={fresh_pct:.1%} < 5%"
                            )
                            self._send_telegram_alert_async(
                                f"⚠️ *WS Cache SEVERELY DEGRADED*\n\n"
                                f"Fresh: {snap['fresh']}/{snap['total']} ({fresh_pct:.1%})\n"
                                f"WS appears to have stopped pushing ticks.\n"
                                f"Auto-recovery will begin in 30s if not resolved."
                            )

                # Canonical health log line
                logger.info(
                    f"[WS Cache] CACHE HEALTH | Fresh: {snap['fresh']}/{snap['total']} ({fresh_pct:.1%}) "
                    f"| Stale: {snap['stale']} | Seeded: {snap.get('seeded', 0)} | Missing: {snap['missing']} "
                    f"| Age P50: {snap['age_p50']:.1f}s P95: {snap['age_p95']:.1f}s "
                    f"| Known: {known_pct:.1%} | State: {self._health_state.value} | Status: {classified.value}"
                )

                # Recovery trigger
                if self._severe_degraded_since > 0 and current not in recovery_states:
                    elapsed_severe = time.time() - self._severe_degraded_since
                    if elapsed_severe >= 30:
                        logger.critical(
                            f"[WS Cache] 🔄 SEVERE DEGRADED for {elapsed_severe:.0f}s "
                            f"(fresh={fresh_pct:.1%}) — triggering auto-recovery"
                        )
                        self._trigger_reprime()

                # CRITICAL path: 5-50% fresh for 2 consecutive cycles.
                elif classified == BrokerHealthState.CRITICAL:
                    if not hasattr(self, "_consecutive_critical_count"):
                        self._consecutive_critical_count = 0
                    self._consecutive_critical_count += 1
                    if self._consecutive_critical_count >= 2:
                        logger.critical(
                            f"[WS Cache] CACHE CRITICAL FOR 60s — Fresh only {fresh_pct:.1%}. Triggering re-prime."
                        )
                        self._trigger_reprime()
                        self._consecutive_critical_count = 0
                else:
                    self._consecutive_critical_count = 0

                # UNRECOVERABLE banner
                if self._health_state == BrokerHealthState.UNRECOVERABLE:
                    logger.critical(
                        "[WS Cache] ⛔ UNRECOVERABLE — "
                        "running on REST fallback for session remainder. Manual restart recommended."
                    )

            except Exception as e:
                logger.error(f"[WS Cache] Health monitor error: {e}")

    async def _subscribe_quietly(self, symbol: str) -> None:
        """Best-effort tick subscription, off the order critical path."""
        try:
            await self.subscribe_symbols([symbol])
        except Exception as e:
            logger.debug("Background subscribe failed for %s: %s", symbol, e)

    async def subscribe_symbols(self, symbols: list[str]):
        """Subscribe to real-time data for symbols."""
        new_symbols = [s for s in symbols if s not in self.subscribed_symbols]
        if new_symbols and self.data_ws:
            try:
                # subscribe() only queues a message on the socket, so it is
                # called directly rather than pushed through an executor.
                self.data_ws.subscribe(symbols=new_symbols, data_type="SymbolUpdate")
                self.subscribed_symbols.update(new_symbols)
                logger.info(f"Subscribed to {len(new_symbols)} symbols via WebSocket")
            except Exception as e:
                logger.error(f"Symbol subscription failed: {e}")

    # REST API Wrappers with Rate Limit

    ORDER_PRIORITY_ENDPOINTS = frozenset(
        {
            "place_order",
            "cancel_order",
            "modify_order",
            "get_order_status",
        }
    )

    async def _rate_limit_wait(self, endpoint: str):
        """
        Enforce global rate limits.

        Order-path endpoints acquire at HIGH priority so a stop-loss placement is
        never queued behind hundreds of scanner quote calls.
        """
        priority = Priority.HIGH if endpoint in self.ORDER_PRIORITY_ENDPOINTS else Priority.NORMAL
        await rest_limiter.acquire_async(priority=priority)

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        order_type: str = "MARKET",
        price: float = 0,
        trigger_price: float = 0,
        order_tag: str | None = None,
    ) -> str:
        """
        Place an order via REST.

        The fill-notification Event is registered BEFORE the HTTP call returns is
        impossible (we need the id), so instead we register it immediately on
        receipt and then replay any order update that already landed in the cache
        during that window — otherwise a fast fill can be missed entirely.
        """
        await self._rate_limit_wait("place_order")

        try:
            # Subscription is for tick data, NOT for order placement — it has no
            # bearing on whether the order succeeds. It used to be awaited here,
            # putting a websocket round-trip (565ms on 2026-08-07, including the
            # server ACK) directly in front of every order. Fire it off and move on.
            if symbol not in self.subscribed_symbols:
                asyncio.create_task(self._subscribe_quietly(symbol))

            data = {
                "symbol": symbol,
                "qty": qty,
                "type": 2 if order_type == "MARKET" else 1,
                "side": 1 if side == "BUY" else -1,
                "productType": "INTRADAY",
                "validity": "DAY",
                "offlineOrder": False,
            }
            if order_type == "LIMIT":
                data["limitPrice"] = price
            elif order_type == "SL_MARKET":
                data["type"] = 3  # Fyers type 3 = SL-Market (trigger only, guaranteed fill)
                data["stopPrice"] = trigger_price
                data["limitPrice"] = 0
            elif order_type == "SL_LIMIT":
                data["type"] = 4  # Fyers type 4 = SL-Limit
                data["stopPrice"] = trigger_price
                data["limitPrice"] = price

            if order_tag:
                # Echoed back on every order/trade event — useful for correlating
                # an execution to the signal that caused it.
                data["orderTag"] = str(order_tag)[:20]

            loop = asyncio.get_event_loop()

            async def _place():
                return await loop.run_in_executor(None, self.rest_client.place_order, data)

            try:
                # MUST exceed the HTTP read timeout — otherwise this fires first and
                # abandons a request the transport would have resolved cleanly.
                response = await asyncio.wait_for(_place(), timeout=ASYNC_CALL_TIMEOUT)
            except TimeoutError:
                # A timeout is NOT proof the order failed — it may be live at the
                # exchange. Surface it distinctly so callers reconcile before retry.
                raise OrderPlacementTimeout(
                    f"place_order timed out after {ASYNC_CALL_TIMEOUT:.0f}s for "
                    f"{symbol} {side} x{qty}; order may or may not be live — "
                    f"reconcile before retrying"
                )

            if isinstance(response, dict) and response.get("s") == "ok":
                order_id = str(response["id"])
                # Every order the bot places passes through here, so this set is the
                # complete answer to "did we place this?". Manual-override detection
                # needs it: without it the bot's own partial-exit order looks exactly
                # like an operator's, and on 2026-09-08 it stood down from
                # NSE:ASIANENE-EQ 131ms after its own TP-1 scale-out.
                self.bot_order_ids.add(order_id)
                self.order_fill_events.setdefault(order_id, asyncio.Event())
                # If an update for this id already arrived, don't wait for another.
                if order_id in self.order_status_cache:
                    self._signal_order_waiters(order_id)
                logger.info(
                    "Order placed: %s %s %s x%s%s",
                    order_id,
                    side,
                    symbol,
                    qty,
                    f" ({order_type})" if order_type != "MARKET" else "",
                )
                return order_id

            raise Exception(f"Order placement failed: {response}")
        except Exception as e:
            logger.error(f"place_order error: {e}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        await self._rate_limit_wait("cancel_order")
        try:
            loop = asyncio.get_event_loop()
            data = {"id": order_id}

            async def _cancel():
                return await loop.run_in_executor(None, self.rest_client.cancel_order, data)

            try:
                response = await asyncio.wait_for(_cancel(), timeout=ASYNC_CALL_TIMEOUT)
            except TimeoutError:
                logger.warning(f"Fyers API cancel_order timeout for {order_id}")
                return False

            if response["s"] == "ok":
                logger.info(f"Order cancelled: {order_id}")
                return True
            else:
                logger.warning(f"Cancel order failed: {response}")
                return False
        except Exception as e:
            logger.error(f"cancel_order error: {e}")
            return False

    async def wait_for_fill(self, order_id: str, timeout: float = 15.0) -> bool:
        """
        Wait until the order reaches a TERMINAL state. Returns True only if FILLED.

        Two defects made the previous version resolve incorrectly on every order:

        1. It returned after the FIRST websocket event. Fyers emits TRANSIT (4) and
           PENDING (6) before FILLED (2) — in this account's logs status 4 is the
           single most common frame — so the first event almost never meant "filled".
        2. It compared against the string 'FILLED' while the socket delivers numeric
           codes.

        We now loop until a terminal status, with a periodic REST reconcile so a
        genuinely dropped websocket frame still resolves well inside the timeout
        instead of burning the full budget.
        """
        order_id = str(order_id)
        loop = asyncio.get_event_loop()
        event = self.order_fill_events.setdefault(order_id, asyncio.Event())
        deadline = loop.time() + timeout
        rest_probe_interval = 3.0
        next_rest_probe = loop.time() + rest_probe_interval

        try:
            while True:
                # Clear BEFORE inspecting: any update landing after this point sets
                # the event, so the wait below returns immediately and we re-check.
                event.clear()

                cached = self.order_status_cache.get(order_id)
                if cached is not None:
                    status = FyersOrderStatus.coerce(cached.status)
                    if status in TERMINAL_ORDER_STATUSES:
                        if status is FyersOrderStatus.FILLED:
                            logger.info(
                                "✅ Fill confirmed via WS: %s @ ₹%s",
                                order_id,
                                self._fill_prices.get(order_id, cached.avg_price),
                            )
                            return True
                        logger.warning(
                            "Order %s terminal but not filled: %s%s",
                            order_id,
                            status.name,
                            f" — {cached.message}" if cached.message else "",
                        )
                        return False

                now = loop.time()
                remaining = deadline - now
                if remaining <= 0:
                    break

                # Periodic REST reconcile guards against a dropped WS frame.
                if now >= next_rest_probe:
                    next_rest_probe = now + rest_probe_interval
                    rest_status = await self._check_order_status_rest(order_id)
                    if rest_status in TERMINAL_ORDER_STATUSES:
                        logger.warning(
                            "Order %s resolved via REST probe (WS frame missed): %s",
                            order_id,
                            rest_status.name,
                        )
                        return rest_status is FyersOrderStatus.FILLED

                try:
                    await asyncio.wait_for(
                        event.wait(),
                        timeout=min(remaining, rest_probe_interval),
                    )
                except TimeoutError:
                    continue  # fall through to the next status/REST check

            # Timed out — one last authoritative check before declaring failure.
            final = await self._check_order_status_rest(order_id)
            if final is FyersOrderStatus.FILLED:
                logger.warning(
                    "Order %s filled but no terminal WS frame arrived within %.0fs.",
                    order_id,
                    timeout,
                )
                return True

            logger.warning(
                "Order %s fill timeout after %.0fs (last known status: %s)",
                order_id,
                timeout,
                final.name if final else "unknown",
            )
            return False

        finally:
            self.order_fill_events.pop(order_id, None)

    async def get_tick_size(self, symbol: str) -> float | None:
        """
        The symbol's real minimum price increment, from the broker.

        BUG-2026-08-30: the adoption path defaulted to 0.05 because the position
        payload carries no tick size. Verified against the live API, that is
        wrong in both directions:

            NSE:TIINDIA-EQ     0.1     NSE:SBIN-EQ    0.1
            NSE:CAMLINFINE-EQ  0.01

        A 0.05-rounded stop on a 0.1-tick symbol is rejected outright
        ("StopPrice not a multiple of tick size 0.1000"), which on 18 Aug left a
        position naked for 27 minutes. NSE revised its tick bands in April 2025,
        so this cannot be inferred from price and must be looked up.

        Cached for the session; ticks do not change intraday. Returns None when
        unavailable so the caller can fall back rather than assume.
        """
        symbol = str(symbol)
        if not hasattr(self, "_tick_cache"):
            self._tick_cache = {}
        if symbol in self._tick_cache:
            return self._tick_cache[symbol]

        try:
            await self._rate_limit_wait("depth")
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    self.rest_client.depth,
                    data={"symbol": symbol, "ohlcv_flag": "1"},
                ),
                timeout=ASYNC_CALL_TIMEOUT,
            )
            rec = ((resp or {}).get("d") or {}).get(symbol) or {}
            tick = rec.get("tick_Size")
            if tick and float(tick) > 0:
                self._tick_cache[symbol] = float(tick)
                logger.info("[TICK] %s tick_size=%s (from broker depth)", symbol, tick)
                return float(tick)
            logger.warning("[TICK] depth for %s carried no tick_Size", symbol)
        except Exception as exc:
            logger.warning("[TICK] could not read tick size for %s: %s", symbol, exc)
        return None

    async def get_order_avg_price(self, order_id: str) -> float:
        """
        Average fill price.

        Prefers the volume-weighted price accumulated from trade events, which is
        exact across partial fills. Falls back to the order frame, then REST.
        """
        order_id = str(order_id)

        traded = self._fill_prices.get(order_id)
        if traded:
            return float(traded)

        cached = self.order_status_cache.get(order_id)
        if cached is not None and cached.avg_price:
            return float(cached.avg_price)

        await self._rate_limit_wait("get_order_status")
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, self.rest_client.orderbook),
                timeout=ASYNC_RETRIED_TIMEOUT,
            )
            if isinstance(response, dict) and response.get("s") == "ok":
                for order in response.get("orderBook", []):
                    if str(order.get("id")) == order_id:
                        for key in ("tradedPrice", "tradePrice", "limitPrice"):
                            val = order.get(key, 0)
                            if val:
                                return float(val)
        except TimeoutError:
            logger.warning("Order price query timed out for %s", order_id)
        except Exception as e:
            logger.error(f"Order price query error: {e}")
        return 0.0

    async def get_ltp(self, symbol: str) -> float | None:
        """Get Last Traded Price (uses WebSocket tick cache, falls back to REST)."""
        # Try WebSocket cache first (0ms latency)
        if symbol in self.tick_cache and self.tick_cache[symbol]:
            latest_tick = self.tick_cache[symbol][-1]
            age = (datetime.now(UTC) - latest_tick.timestamp).total_seconds()
            if age < 5.0:  # Cache valid for 5 seconds
                return latest_tick.ltp

        # Fallback to REST API
        await self._rate_limit_wait("get_quotes")
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, self.rest_client.quotes, {"symbols": symbol}
            )
            if response["s"] == "ok" and "d" in response:
                return response["d"][0]["v"]["lp"]
            return None
        except Exception as e:
            logger.error(f"Get LTP error: {e}")
            return None

    async def _check_order_status_rest(self, order_id: str) -> FyersOrderStatus | None:
        """
        Authoritative order status from the orderbook. Returns None when unknown.

        Also back-fills the local caches, so a terminal state discovered here is
        visible to wait_for_fill and get_order_avg_price without a second call.
        """
        order_id = str(order_id)
        await self._rate_limit_wait("get_order_status")
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, self.rest_client.orderbook),
                timeout=ASYNC_RETRIED_TIMEOUT,
            )
            if not isinstance(response, dict) or response.get("s") != "ok":
                return None

            for order in response.get("orderBook", []):
                if str(order.get("id")) != order_id:
                    continue

                status = FyersOrderStatus.coerce(order.get("status"))
                if status is None:
                    return None

                # Back-fill caches so subsequent lookups are free and consistent.
                self.order_status_cache[order_id] = OrderUpdate(
                    {**order, "id": order_id, "status": status}
                )
                if status is FyersOrderStatus.FILLED:
                    for key in ("tradedPrice", "tradePrice"):
                        px = order.get(key, 0)
                        if px:
                            self._fill_prices.setdefault(order_id, float(px))
                            break
                return status

            return None
        except TimeoutError:
            logger.warning("Order status query timed out for %s", order_id)
            return None
        except Exception as e:
            logger.error(f"Order status query error: {e}")
            return None

    async def get_funds(self) -> dict:
        """
        Fetch available margin from Fyers /funds endpoint.
        Rate-limit aware — backs off 180s after a -429 response.
        Phase PRD-WS 4: Hard 15s timeout — returns cached value on timeout, never blocks runtime.
        """
        # Rate-limit cooldown check
        if hasattr(self, "_funds_rate_limited_until"):
            now = datetime.now(UTC)
            if now < self._funds_rate_limited_until:
                remaining = (self._funds_rate_limited_until - now).total_seconds()
                if self._last_cached_funds:
                    logger.warning(
                        f"[RATE-LIMIT] Fyers funds rate-limited ({remaining:.0f}s left). Using cached value."
                    )
                    return {**self._last_cached_funds, "cached": True}
                raise ValueError(f"Fyers funds API rate-limited, retry in {remaining:.0f}s")

        async def _fetch():
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.rest_client.funds)

        try:
            response = await asyncio.wait_for(_fetch(), timeout=15.0)
            if response and response.get("s") == "ok":
                self._last_cached_funds = response  # cache for fallback
                return response
            # Check for rate limit response
            if response and response.get("code") == -429:
                self._funds_rate_limited_until = datetime.now(UTC) + timedelta(seconds=180)
                logger.warning("[RATE-LIMIT] Fyers funds API returned -429. Backing off for 180s.")
            raise ValueError(f"Fyers funds API error: {response}")
        except TimeoutError:
            self._capital_sync_timeout_count += 1
            logger.warning(
                f"[CAPITAL] get_funds timed out (15s). Timeout #{self._capital_sync_timeout_count}. "
                f"Using cached value."
            )
            if self._last_cached_funds:
                return {**self._last_cached_funds, "cached": True}
            raise
        except Exception as e:
            # Also detect rate limit in the error message
            if "-429" in str(e) or "Request limit" in str(e):
                self._funds_rate_limited_until = datetime.now(UTC) + timedelta(seconds=180)
                logger.warning("[RATE-LIMIT] Fyers funds API rate-limited. Backing off for 180s.")
            logger.error(f"get_funds failed: {e}")
            raise

    def get_symbol_leverage_sync(self, symbol: str, price: float) -> float | None:
        """
        Intraday (MIS) leverage the broker will actually grant on this symbol.

        leverage = price / margin_required_for_one_share

        Returns None when the answer is unknown — a failed lookup is not
        evidence of anything, and the caller must fail OPEN on it. Returning a
        number here is what broke this the last time: the old version fell back
        to 5.0 on error, so the guard silently passed everything, and an earlier
        version blocked instead and produced a session with zero trades
        (removed in cd178cc, Apr 2026).

        Two faults made that fallback fire on every single call:

          1. It posted to api.fyers.in/api/v3/multiorder/margin. That host
             answers 500 "Invalid Request, please provide valid method" for
             every symbol. The SDK's own base is api-t1.fyers.in — verified
             2026-08-31, where the same request returns 200.
          2. It read response['data'][0]['margin'], i.e. a list. The real
             response is a dict:
                 {"code":200,"data":{"margin_avail":...,"margin_total":...,
                                     "margin_new_order":212.31,"prevMargin":0},"s":"ok"}

        Measured on the 22 candidates of 2026-08-31, the distribution is
        strictly bimodal — 12 symbols at 4.0x/4.99x, 10 at exactly 1.0x, and
        nothing in between. At 1.0x the required margin equals the share price
        (NSE:SHIPROCKET-EQ: 138.93 margin on a 138.89 share), which is the
        broker's way of saying MIS is not available. That symbol reached an
        order and was rejected with
        "RED:RULE:{Allowed Basket} in Basket NSE.MIS.NSE_MIS_BASKET".
        """
        if not symbol or not price or price <= 0:
            return None

        # Confirmed low-leverage earlier this session; the answer does not
        # change intraday, so never ask again.
        if symbol in self._low_leverage_blacklist:
            return 1.0

        with self._leverage_cache_lock:
            if symbol in self._leverage_cache:
                return self._leverage_cache[symbol]

        try:
            payload = {
                "data": [
                    {
                        "symbol": symbol,
                        "qty": 1,
                        "side": -1,  # SELL — the side this bot actually takes
                        "type": 2,  # market
                        "productType": "INTRADAY",
                        "limitPrice": 0,
                        "stopPrice": 0,
                    }
                ]
            }
            # Build the URL from the SDK's own base rather than hardcoding a
            # host. The previous hardcoded api.fyers.in is what made every call
            # fail; if the vendor moves the base again, the SDK moves with it.
            base = getattr(fyersModel.Config, "API", "https://api-t1.fyers.in/api/v3").rstrip("/")
            headers = {
                "Authorization": f"{self.client_id}:{self.access_token}",
                "Content-Type": "application/json",
            }
            # Counts against the same account-wide budget as every SDK call, so it
            # goes through the same limiter. Every one of the 54 failures over
            # 7-10 Sep was an HTTP 429 from skipping it.
            rest_limiter.acquire()
            resp = requests.post(
                f"{base}/multiorder/margin", headers=headers, json=payload, timeout=8
            )
            response = resp.json() if resp.status_code == 200 else {}

            data = response.get("data") if isinstance(response, dict) else None
            margin = (data or {}).get("margin_new_order") if isinstance(data, dict) else None

            if margin and margin > 0:
                leverage = round(price / margin, 2)
                with self._leverage_cache_lock:
                    self._leverage_cache[symbol] = leverage
                logger.info(
                    "[BROKER] %s leverage %.2fx (margin ₹%.2f on a ₹%.2f share)",
                    symbol,
                    leverage,
                    margin,
                    price,
                )
                # A confirmed reading below the floor is permanent for the day.
                if leverage < getattr(config, "SCANNER_MIN_LEVERAGE", 3.5):
                    self._low_leverage_blacklist.add(symbol)
                return leverage

            logger.warning(
                "[BROKER] leverage lookup for %s returned HTTP %s / %s — unknown, "
                "caller must fail open",
                symbol,
                resp.status_code,
                str(response)[:120],
            )
            return None

        except Exception as e:
            logger.error("[BROKER] leverage lookup failed for %s: %s", symbol, e)
            return None

    # A WS position snapshot older than this is not trusted for reconciliation.
    POSITION_CACHE_TTL_SECONDS = 30.0

    @staticmethod
    def _normalise_position(raw: dict) -> dict:
        """
        Normalise a position record to one shape every consumer can rely on.

        Fyers returns BOTH `qty` (absolute) and `netQty` (signed, negative for
        shorts). Different call sites in this codebase read different keys, so a
        record missing either one produced silent zeros. Always emit both, plus
        the aliases already in use.
        """
        net = raw.get("netQty", raw.get("net_qty", 0)) or 0
        try:
            net = int(net)
        except (TypeError, ValueError):
            net = 0

        qty = raw.get("qty")
        try:
            qty = abs(int(qty)) if qty is not None else abs(net)
        except (TypeError, ValueError):
            qty = abs(net)

        avg = raw.get("avgPrice") or raw.get("netAvg") or raw.get("avg_price") or 0.0
        # For a short, sellAvg is the true entry; for a long, buyAvg.
        if not avg:
            avg = raw.get("sellAvg", 0) if net < 0 else raw.get("buyAvg", 0)

        return {
            **raw,
            "symbol": raw.get("symbol"),
            "qty": qty,
            "netQty": net,
            "avgPrice": float(avg or 0.0),
            "side": "SHORT" if net < 0 else ("LONG" if net > 0 else "FLAT"),
            "productType": raw.get("productType", "INTRADAY"),
            "realized_profit": raw.get("realized_profit", 0) or 0,
            "unrealized_profit": raw.get("unrealized_profit", 0) or 0,
        }

    async def get_all_positions(self, force_rest: bool = False) -> list[dict]:
        """
        All open positions — WS cache first, REST fallback.

        The cache is now genuinely populated (see _handle_position_update), so the
        common path costs zero REST calls. Previously nothing ever wrote to
        position_cache, so this silently hit REST on every single invocation —
        including every 6s reconciliation cycle.

        force_rest=True bypasses the cache for the authoritative pre-exit check.
        """
        if not force_rest:
            now = datetime.now(UTC)
            with self._position_cache_lock:
                snapshot = list(self.position_cache.items())

            fresh = [
                self._normalise_position(
                    {
                        "symbol": symbol,
                        "netQty": p.net_qty,
                        "qty": abs(p.net_qty),
                        "avgPrice": p.avg_price,
                        "realized_profit": p.realized_pnl,
                        "unrealized_profit": p.unrealized_pnl,
                        **(p.raw_data or {}),
                    }
                )
                for symbol, p in snapshot
                if p.net_qty != 0
                and (now - p.timestamp).total_seconds() < self.POSITION_CACHE_TTL_SECONDS
            ]
            if fresh:
                return fresh

        # Cache empty or stale. Note: empty cache legitimately means "flat", so we
        # still verify via REST rather than assuming — being wrong about flat is
        # how a naked position goes unnoticed.
        await self._rate_limit_wait("get_positions")
        try:

            async def _fetch_positions():
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self.rest_client.positions)

            response = await asyncio.wait_for(_fetch_positions(), timeout=ASYNC_RETRIED_TIMEOUT)
            if isinstance(response, dict) and response.get("s") == "ok":
                return [
                    self._normalise_position(pos)
                    for pos in response.get("netPositions", [])
                    if (pos.get("netQty", 0) or 0) != 0
                ]
            # Reached only when the broker answered with something that is not a
            # position list — a 429, an auth failure, a malformed body. None of
            # those mean "flat", so none of them may return a list.
            logger.warning("get_all_positions: unexpected response: %s", response)
            raise PositionFetchError(f"broker returned {response}")
        except TimeoutError:
            self._reconcile_timeout_count += 1
            logger.warning(
                "[RECONCILE] get_all_positions timed out (10s). Timeout #%d.",
                self._reconcile_timeout_count,
            )
            raise PositionFetchError("positions fetch timed out")
        except PositionFetchError:
            raise
        except Exception as e:
            logger.error(f"Get all positions error: {e}")
            raise PositionFetchError(str(e)) from e

    async def shutdown(self):
        logger.info("Shutting down broker interface...")
        for task in self.tasks:
            task.cancel()

        # Sockets are left to the SDK: it exposes no reliable async close.
        pass

    async def disconnect(self):
        """
        Cleanly stop WebSocket threads. Called during cleanup_runtime().
        """
        logger.info("[BROKER] Disconnecting WebSocket connections...")

        # Stop the health monitor thread
        health_thread = getattr(self, "_health_monitor_thread", None)
        if health_thread and health_thread.is_alive():
            # Signal the thread to stop — set a stop flag it checks
            self._ws_cache_stop = True
            health_thread.join(timeout=3.0)
            logger.info("[BROKER] Health monitor thread stopped.")

        # Stop data WebSocket
        try:
            data_ws = getattr(self, "data_ws", None) or getattr(self, "_data_ws", None)
            if data_ws:
                # Fyers SDK may use stop()/disconnect() instead of close()
                _stopped = False
                for _method in ("stop", "disconnect", "close"):
                    fn = getattr(data_ws, _method, None)
                    if callable(fn):
                        await asyncio.to_thread(fn)
                        logger.info(f"[BROKER] Data WebSocket closed via .{_method}().")
                        _stopped = True
                        break
                if not _stopped:
                    logger.warning(
                        "[BROKER] Data WebSocket: no stop/disconnect/close method found (non-fatal)."
                    )
        except Exception as e:
            logger.warning(f"[BROKER] Data WS close error (non-fatal): {e}")

        # Stop order WebSocket
        try:
            order_ws = getattr(self, "order_ws", None) or getattr(self, "_order_ws", None)
            if order_ws:
                # Fyers SDK may use stop()/disconnect() instead of close()
                _stopped = False
                for _method in ("stop", "disconnect", "close"):
                    fn = getattr(order_ws, _method, None)
                    if callable(fn):
                        await asyncio.to_thread(fn)
                        logger.info(f"[BROKER] Order WebSocket closed via .{_method}().")
                        _stopped = True
                        break
                if not _stopped:
                    logger.warning(
                        "[BROKER] Order WebSocket: no stop/disconnect/close method found (non-fatal)."
                    )
        except Exception as e:
            logger.warning(f"[BROKER] Order WS close error (non-fatal): {e}")

        logger.info("[BROKER] Disconnect complete.")
