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


"""Position sizing and single-slot capital accounting.

Available margin is read from Fyers GET /funds rather than configured, so
sizing tracks the real account. The bot holds one position at a time, enforced
by acquire_slot() / release_slot().

The slot check is deliberately separate from the execution block: a caller can
ask whether capital is available without being hard-blocked, which is what lets
a signal be fully observed and logged for ML even when it cannot be traded.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from math import floor

logger = logging.getLogger(__name__)


class CapitalManager:
    """
    Live-synced capital tracker.
    Source of truth: Fyers GET /funds → available_margin.
    NOT the hardcoded base_capital from config.
    """

    def __init__(self, leverage: float = 5.0):
        self.leverage = leverage
        self._real_margin: float = 0.0  # always from Fyers, never hardcoded
        self._initial_margin: float = 0.0  # starting ledger for the day (Dynamic Target base)
        self._last_sync: datetime | None = None
        self._position_active: bool = False
        self._active_symbol: str | None = None
        self._lock = asyncio.Lock()

        logger.info(
            f"💰 Capital Manager initialized | leverage={leverage}x | "
            f"real_margin=PENDING (call sync() before trading)"
        )

    # Properties

    @property
    def buying_power(self) -> float:
        return self._real_margin * self.leverage

    @property
    def is_slot_free(self) -> bool:
        return not self._position_active

    @property
    def active_symbol(self) -> str | None:
        return self._active_symbol

    @property
    def initial_margin(self) -> float:
        return self._initial_margin

    # Fyers Sync

    async def sync(self, broker) -> float:
        """
        Pull actual available_margin from Fyers.

        Call schedule:
          - Session start (before first scan)
          - After every confirmed fill
          - After every position close (SL/TP/manual)
          - Every 5 minutes in health monitor heartbeat

        Returns: real_margin (float)
        """
        async with self._lock:
            try:
                funds = await broker.get_funds()
                margin = self._parse_fyers_funds(funds)
                self._real_margin = margin
                self._last_sync = datetime.now(UTC)

                # Capture morning ledger for dynamic goals (5% target)
                if self._initial_margin == 0.0:
                    self._initial_margin = margin
                    logger.info(
                        f"🎯 [INITIAL CAPITAL] Captured morning balance: ₹{self._initial_margin:.2f}"
                    )

                logger.info(
                    f"💰 CAPITAL SYNC | real_margin=₹{self._real_margin:.2f} | "
                    f"buying_power=₹{self.buying_power:.2f} | "
                    f"slot={'OCCUPIED → ' + (self._active_symbol or '?') if self._position_active else 'FREE'} | "
                    f"synced_at={self._last_sync.strftime('%H:%M:%S')}"
                )
                return self._real_margin

            except Exception as e:
                logger.error(
                    f"💰 CAPITAL SYNC FAILED: {e} | keeping last value ₹{self._real_margin:.2f}"
                )
                return self._real_margin

    def _parse_fyers_funds(self, funds: dict) -> float:
        """
        Parse Fyers /funds response — handles multiple API response shapes.

        Fyers v3 /funds returns:
          { "s": "ok", "fund_limit": [
              {"id": 1, "title": "Total Balance",     "equityAmount": 1800.00},
              {"id": 2, "title": "Available Balance", "equityAmount": 1700.00},
              ...
          ]}

        We want id=2 "Available Balance".
        """
        if not isinstance(funds, dict) or funds.get("s") != "ok":
            raise ValueError(f"Fyers funds response invalid: {funds}")

        # Pattern 1: fund_limit list (Fyers v3 standard)
        best_val = 0.0
        for item in funds.get("fund_limit", []):
            # id=10 is "Available Balance" in Fyers v3. id=1 is "Total Balance".
            # id=2 is "Utilized Amount" (which was causing the bot to size based on used margin!)
            val = float(item.get("equityAmount", 0) or 0)
            title = str(item.get("title", "")).lower()

            if item.get("id") == 10 or "available" in title:
                if val > 100:  # Threshold for "normal" account balance
                    return val
                best_val = max(best_val, val)

            # Fallback to id=1 (cash) if id=10 is missing
            if item.get("id") == 1 or "total" in title:
                best_val = max(best_val, val)

        if best_val > 0:
            return best_val

        # Pattern 2: equity dict (some Fyers SDK wrappers)
        eq = funds.get("equity", {})
        if isinstance(eq, dict):
            for key in ("available_margin", "availableMargin", "available", "cash_balance"):
                if key in eq:
                    return float(eq[key] or 0)

        # Pattern 3: flat dict
        for key in ("available_margin", "availableMargin", "available_balance", "cashBalance"):
            if key in funds:
                return float(funds[key] or 0)

        logger.warning(f"Abnormal funds structure detected: {json.dumps(funds)}")
        raise ValueError("Cannot parse available margin from Fyers funds.")

    # Sizing

    def compute_qty(self, symbol: str, ltp: float, dynamic_leverage: float = None) -> tuple:
        """
        Compute maximum qty for FULL margin utilization.

        Uses real Fyers margin (not virtual/hardcoded) and actual leverage for the symbol.
        Applies 2% safety buffer to avoid Fyers code -50.

        Returns: (qty: int, cost: float, margin_required: float)
        """
        if ltp <= 0 or self._real_margin <= 0:
            return 0, 0.0, 0.0

        if dynamic_leverage is None:
            dynamic_leverage = self.leverage

        safety_cap = self._real_margin * 0.98  # 2% safety buffer

        # Calculate buying power based on true dynamic leverage
        true_buying_power = self._real_margin * dynamic_leverage
        raw_qty = true_buying_power / ltp
        qty = int(floor(raw_qty))

        # Walk down until margin fits within safety cap
        while qty > 0:
            cost = qty * ltp
            margin_req = cost / dynamic_leverage
            if margin_req <= safety_cap:
                utilization = (margin_req / self._real_margin) * 100
                logger.info(
                    f"💰 SIZING {symbol} | real_margin=₹{self._real_margin:.2f} "
                    f"buying_power=₹{true_buying_power:.2f} (Lev: {dynamic_leverage}x) | ltp=₹{ltp:.2f} "
                    f"raw={raw_qty:.2f} → qty={qty} | cost=₹{cost:.2f} "
                    f"margin_req=₹{margin_req:.2f} | utilization={utilization:.1f}%"
                )
                return qty, cost, margin_req
            qty -= 1

        logger.warning(
            f"💰 SIZING {symbol} — ZERO QTY | "
            f"real_margin=₹{self._real_margin:.2f} ltp=₹{ltp:.2f} "
            f"(stock costs more than available margin)"
        )
        return 0, 0.0, 0.0

    # Slot Management (Single-Position Architecture)

    async def acquire_slot(self, symbol: str):
        """
        Lock capital slot after confirmed fill.
        Call AFTER broker confirms fill, BEFORE SL placement.
        """
        async with self._lock:
            if self._position_active:
                raise RuntimeError(
                    f"Slot occupied by {self._active_symbol} — cannot acquire for {symbol}"
                )
            self._position_active = True
            self._active_symbol = symbol
            logger.info(
                f"💰 CAPITAL SLOT ACQUIRED → {symbol} | "
                f"margin_committed=₹{self._real_margin:.2f} | "
                f"all new entries BLOCKED until position closes"
            )

    # Must not outlive the close path that triggered it: get_funds allows 15s but
    # focus_engine waits only 10s, so a finalize once reported FAILED while the
    # work completed 5s later. Releasing the slot is instant and is what matters;
    # the margin number may lag.
    RELEASE_SYNC_TIMEOUT = 6.0

    async def release_slot(self, broker=None):
        """
        Release capital slot after SL/TP/manual exit.
        Re-syncs Fyers margin if broker is provided, without blocking the caller.
        """
        async with self._lock:
            released = self._active_symbol
            self._position_active = False
            self._active_symbol = None
            logger.info(f"💰 CAPITAL SLOT RELEASED ← {released}")

        # Sync outside the lock — avoids deadlock, refreshes margin for the next trade.
        if not broker:
            return
        try:
            await asyncio.wait_for(self.sync(broker), timeout=self.RELEASE_SYNC_TIMEOUT)
        except TimeoutError:
            # Finish the refresh in the background; the slot is already free, which
            # is the only part the caller is waiting on.
            logger.warning(
                "[CAPITAL] Margin refresh exceeded %.0fs after releasing %s — "
                "continuing in background (slot is already free).",
                self.RELEASE_SYNC_TIMEOUT,
                released,
            )
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self._background_sync(broker))
        except Exception as e:
            logger.error(f"[CAPITAL] Margin refresh failed after release: {e}")

    async def _background_sync(self, broker):
        """Best-effort margin refresh detached from any caller's timeout."""
        try:
            await self.sync(broker)
        except Exception as e:
            logger.error(f"[CAPITAL] Background margin sync failed: {e}")

    def get_slot_status(self) -> dict:
        """Rich status dict — used in Telegram capital alerts."""
        return {
            "slot_free": self.is_slot_free,
            "active_symbol": self._active_symbol,
            "real_margin": self._real_margin,
            "buying_power": self.buying_power,
            "leverage": self.leverage,
            "last_sync": self._last_sync.strftime("%H:%M:%S") if self._last_sync else "NEVER",
        }

    # Legacy Compatibility (keeps existing callers working)

    def get_status(self) -> dict:
        """Legacy-compatible — used by order_manager for buying_power lookup."""
        return {
            "base_capital": self._real_margin,
            "leverage": self.leverage,
            "total_buying_power": self.buying_power,
            "available": self.buying_power if self.is_slot_free else 0.0,
            "in_use": self.buying_power if not self.is_slot_free else 0.0,
            "positions_count": 1 if self._position_active else 0,
            "active_symbol": self._active_symbol,
        }

    def release(self, symbol: str):
        """DEPRECATED — use release_slot(). Kept so old code doesn't crash."""
        logger.warning(
            f"⚠️ capital.release() called [DEPRECATED] for {symbol} — migrate to release_slot()"
        )

    def force_reset_slot(self, reason: str = "EMERGENCY") -> None:
        """
        Synchronously clear the capital slot without awaiting the async lock.

        Last-resort path for reconciliation when the normal async release has
        already failed. Callers previously tried to do this by assigning
        `capital.is_slot_free = True` and `capital.active_symbol = None` — but both
        are read-only @property objects, so the assignment raised AttributeError
        and the slot stayed locked forever, silently blocking every later entry.

        Safe to call from any thread: it only rebinds two attributes, and the
        single-position model means there is nothing to interleave with.
        """
        previous = self._active_symbol
        self._position_active = False
        self._active_symbol = None
        logger.critical(
            "💰 CAPITAL SLOT FORCE-RESET (%s) — was held by %s",
            reason,
            previous or "nothing",
        )
