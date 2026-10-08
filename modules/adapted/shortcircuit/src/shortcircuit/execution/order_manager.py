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


"""Order placement, fill confirmation and stop-loss management.

Owns the full lifecycle of a position at the broker: sizing it against live
Fyers margin, placing the entry, waiting on the order socket for a real fill,
attaching an SL-M stop, and reconciling whatever the broker actually did.

Two invariants run through this module:

  - A capital slot is acquired only after a *confirmed* fill, never on dispatch.
  - An order in TRANSIT or PENDING is still working at the exchange. Treating
    either as dead is how a resting stop-loss gets orphaned.
"""

import asyncio
import contextlib
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from shortcircuit import config
from shortcircuit.broker.fyers_broker_interface import (
    FyersBrokerInterface,
    FyersOrderStatus,
    OrderPlacementTimeout,
    PositionFetchError,
)
from shortcircuit.broker.fyers_connect import ASYNC_RETRIED_TIMEOUT
from shortcircuit.broker.rest_limiter import Priority, rest_limiter
from shortcircuit.observability.ml_logger import get_ml_logger

logger = logging.getLogger(__name__)

# Canonical Fyers status codes live in fyers_broker_interface. These aliases are
# kept so existing comparisons keep reading naturally.
FYERS_ORDER_STATUS_TRADED = int(FyersOrderStatus.FILLED)  # 2
FYERS_ORDER_STATUS_PENDING = int(FyersOrderStatus.PENDING)  # 6
FYERS_ORDER_STATUS_TRANSIT = int(FyersOrderStatus.TRANSIT)  # 4

# An order in TRANSIT or PENDING is still working at the exchange. Treating either
# as "not live" is how a resting stop-loss gets orphaned.
FYERS_STATUS_WORKING = (FYERS_ORDER_STATUS_PENDING, FYERS_ORDER_STATUS_TRANSIT)

EXEC_COOLDOWN_SECONDS = 900  # 15 minutes after any failed entry
# Permanent-for-the-session broker rejections (RMS basket rules, risk CUG).
# Long enough to outlast any trading day, so the symbol is not retried.
SESSION_BLOCK_SECONDS = 8 * 3600


class OrderManager:
    """
    Async Order Manager with WebSocket Support.

    Responsibilities:
    1. Async Execution via FyersBrokerInterface
    2. Zero-latency Fill Detection (WebSocket, 15s timeout with REST fallback)
    3. Full Fyers margin utilization via CapitalManager.compute_qty()
    4. Capital slot acquisition after fill / release after close
    5. Execution failure cooldown (prevents same-symbol spam)
    6. Safe Entry with Immediate Hard Stop (SL-M)
    7. Phantom Fill Prevention (Cancel SL *before* Exit)
    """

    def __init__(
        self,
        broker: FyersBrokerInterface,
        telegram_bot,
        db=None,
        capital_manager=None,
        trade_manager=None,
    ):
        self.broker = broker
        self.telegram = telegram_bot
        self.db = db
        self.capital = capital_manager
        self.trade_manager = trade_manager

        self.active_positions: dict[str, Any] = {}
        self.position_locks: dict[str, asyncio.Lock] = {}
        self.exit_in_progress: dict[str, bool] = {}
        self.hard_stops: dict[str, str] = {}
        self.partial_exits_in_progress: dict[
            str, dict[str, float]
        ] = {}  # {symbol: {reason: timestamp}}

        # Execution failure cooldown tracker
        # { symbol: datetime_unblock }
        self._exec_cooldowns: dict[str, datetime] = {}

        self._warned_no_reconciler = False

    def _notify_reconciler(self, symbol: str, dirty: bool = False) -> None:
        """
        Tell the reconciler we just touched `symbol`, so it does not mistake our
        own position for someone else's.

        The wiring this depends on was absent for the whole life of the feature and
        nothing said so, because the call sites guarded it with `getattr(..., None)`
        and moved on. A missing engine is a deployment fault, not a normal state, so
        it now says so once instead of silently disabling orphan suppression.
        """
        engine = getattr(getattr(self, "trade_manager", None), "reconciliation_engine", None)
        if engine is None:
            if not self._warned_no_reconciler:
                self._warned_no_reconciler = True
                logger.error(
                    "[WIRING] TradeManager has no reconciliation_engine — orphan "
                    "suppression is INACTIVE and every open position will be "
                    "reported as an orphan. Check supervisor back-injection."
                )
            return
        if dirty:
            engine.mark_dirty()
        engine.mark_recently_modified(symbol)

    def _get_lock(self, symbol: str) -> asyncio.Lock:
        if symbol not in self.position_locks:
            self.position_locks[symbol] = asyncio.Lock()
        return self.position_locks[symbol]

    def is_exec_cooldown_active(self, symbol: str) -> tuple:
        """
        Returns (is_active: bool, remaining_seconds: int).
        Used by focus_engine before calling enter_position.
        """
        if symbol not in self._exec_cooldowns:
            return False, 0
        unblock_at = self._exec_cooldowns[symbol]
        now = datetime.now(UTC)
        if now < unblock_at:
            remaining = int((unblock_at - now).total_seconds())
            return True, remaining
        del self._exec_cooldowns[symbol]
        return False, 0

    def _set_exec_cooldown(self, symbol: str, reason: str, seconds: int = 900):
        """Phase 44.6: Block symbol from new entries after local logic failure."""
        unblock_at = datetime.now(UTC) + timedelta(seconds=seconds)
        self._exec_cooldowns[symbol] = unblock_at
        logger.warning(
            f"⏳ [COOLDOWN] {symbol} blocked for {seconds}s | Reason: {reason} | Until: {unblock_at.strftime('%H:%M:%S')}"
        )

    @staticmethod
    def _round_sl_to_tick(price: float, side: str, tick: float = 0.05) -> float:
        """
        Round SL trigger price to nearest valid Fyers tick boundary.

        Fyers rejects SL-M orders where trigger_price % tick_size != 0.
        NSE equities: tick_size varies per stock (0.01, 0.05, 0.10).
        Always use the tick_size from the symbol master, never hardcode.

        Rounding direction (away from entry = more buffer, never tighter):
          SHORT (SELL entry) → SL is above entry → round UP (ceiling)
          LONG  (BUY entry)  → SL is below entry → round DOWN (floor)

        Examples:
          SHORT: 745.16 → ceil(745.16/0.05)*0.05 = ceil(14903.2)*0.05 = 745.20  ✅
          SHORT: 745.20 → 745.20  (already valid, no change)
          LONG:  718.94 → floor(718.94/0.05)*0.05 = floor(14378.8)*0.05 = 718.90  ✅
        """
        import math

        if side == "SELL":  # SHORT trade — SL is above entry
            rounded = math.ceil(price / tick) * tick
        else:  # LONG trade — SL is below entry
            rounded = math.floor(price / tick) * tick
        return round(rounded, 2)

    def compute_stop_loss(self, ltp: float, signal: dict) -> float:
        """
        ATR-based stop, anchored to the setup but VALIDATED against the real fill.

        The stop level comes from the signal's structural level (setup high/low),
        which is captured at signal time. The actual fill can drift past that level
        — and when it does, the stop lands on the WRONG SIDE of the entry and is
        marketable the instant it is placed.

        That is not hypothetical. 2026-08-06, NSE:STOVEKRAFT-EQ:
            signal ₹813.00 → filled SHORT @ ₹821.30 (+1.02% slippage)
            stop computed from signal_high  = ₹816.00   ← BELOW the short entry
            BUY stop @816 with price at ~821 was immediately marketable
            → stopped out 130ms after entry at ₹821.92, realised −₹2.50

        A short's stop must sit ABOVE its entry; a long's BELOW. This enforces that
        invariant against the price we actually got, not the price we hoped for.
        """
        atr = signal.get("atr", 0)
        tick = signal.get("tick_size", 0.05)
        # max(atr * 0.5, 3 * tick_size), both multipliers from config.
        buffer = max(
            atr * getattr(config, "SL_ATR_MULTIPLIER", 0.5),
            tick * getattr(config, "SL_MIN_TICK_BUFFER", 3),
        )

        # Minimum separation between entry and stop, so a corrected stop is not
        # merely "on the right side" but far enough to survive normal spread.
        min_gap = max(buffer, tick * getattr(config, "SL_MIN_TICK_BUFFER", 3))

        direction = config.TRADE_DIRECTION
        if direction == "LONG":
            signal_low = signal.get("signal_low", ltp * 0.99)
            sl_price = signal_low - buffer
            if ltp > 0 and sl_price >= ltp - (min_gap / 2):
                corrected = ltp - min_gap
                logger.critical(
                    "🚨 [SL-GUARD] LONG stop ₹%.2f is at/above fill ₹%.2f — would fire "
                    "instantly. Re-anchoring to fill: ₹%.2f",
                    sl_price,
                    ltp,
                    corrected,
                )
                sl_price = corrected
            return self._round_sl_to_tick(sl_price, "BUY", tick)

        signal_high = signal.get("signal_high", ltp * 1.01)
        sl_price = signal_high + buffer
        if ltp > 0 and sl_price <= ltp + (min_gap / 2):
            corrected = ltp + min_gap
            logger.critical(
                "🚨 [SL-GUARD] SHORT stop ₹%.2f is at/below fill ₹%.2f — would fire "
                "instantly. Re-anchoring to fill: ₹%.2f",
                sl_price,
                ltp,
                corrected,
            )
            sl_price = corrected
        return self._round_sl_to_tick(sl_price, "SELL", tick)

    def validate_stop_against_fill(
        self, symbol: str, entry_price: float, stop_price: float, side: str
    ) -> tuple:
        """
        Final safety gate before a stop is sent to the broker.

        Returns (ok, reason). ok=False means DO NOT place this stop — the caller
        should exit the position at market instead, because a stop on the wrong
        side is not protection, it is a guaranteed immediate round-trip.
        """
        if entry_price <= 0 or stop_price <= 0:
            return False, f"non-positive price (entry={entry_price}, stop={stop_price})"

        if side == "SHORT" and stop_price <= entry_price:
            return False, (f"SHORT stop ₹{stop_price:.2f} is not above entry ₹{entry_price:.2f}")
        if side == "LONG" and stop_price >= entry_price:
            return False, (f"LONG stop ₹{stop_price:.2f} is not below entry ₹{entry_price:.2f}")

        # Sanity ceiling: a stop more than 10% away is almost certainly a bad
        # level rather than a deliberate one, and risks far more than intended.
        risk_pct = abs(stop_price - entry_price) / entry_price * 100
        if risk_pct > 10.0:
            return False, f"stop is {risk_pct:.1f}% from entry — implausible risk"

        return True, f"stop {risk_pct:.2f}% from entry"

    def compute_take_profits(self, entry: float, signal: dict) -> dict:
        """
        Reference VWAP target — INFORMATIONAL ONLY. Not an exit trigger.

        Take-profit exits were removed: the target capped every winner while
        losers still ran to the stop. This is retained purely so the VWAP level
        keeps landing in the ML observation log for later analysis.
        """
        vwap = signal.get("vwap")
        if vwap is not None and vwap > 0:
            tp = vwap
        else:
            direction = config.TRADE_DIRECTION
            tp = entry * (1.01 if direction == "LONG" else 0.99)

        tick = signal.get("tick_size", 0.05)
        return {"tp": round(round(tp / tick) * tick, 2)}

    async def _reconcile_unknown_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        lookback_seconds: int = 60,
        attempts: int = 3,
    ) -> str | None:
        """
        Find an order we may have placed but whose response we never received.

        Called after an OrderPlacementTimeout. Scans the orderbook for a recent
        order matching this symbol/side/qty that is either working or already
        filled. Returns its id if found, else None.

        This is the difference between "the request timed out so nothing happened"
        (usually wrong) and "let me go look" (always correct).

        It RETRIES, because this is the safety net and a single attempt is not
        good enough. On 2026-08-07 the one attempt used a 5s budget against a 12s
        transport timeout, timed out, and the bot proceeded without ever learning
        whether a live SELL order was resting at the broker.
        """
        loop = asyncio.get_event_loop()
        rest = getattr(self.broker, "rest_client", None)
        if not rest:
            logger.error("[RECONCILE-ORDER] No REST client — cannot verify %s", symbol)
            return None

        orderbook = None
        for attempt in range(1, attempts + 1):
            try:
                orderbook = await asyncio.wait_for(
                    loop.run_in_executor(None, rest.orderbook),
                    timeout=ASYNC_RETRIED_TIMEOUT,
                )
                if isinstance(orderbook, dict) and orderbook.get("s") == "ok":
                    break
                logger.warning(
                    "[RECONCILE-ORDER] Attempt %d/%d: bad orderbook response for %s",
                    attempt,
                    attempts,
                    symbol,
                )
            except TimeoutError:
                logger.warning(
                    "[RECONCILE-ORDER] Attempt %d/%d timed out for %s",
                    attempt,
                    attempts,
                    symbol,
                )
            except Exception as e:
                logger.warning(
                    "[RECONCILE-ORDER] Attempt %d/%d failed for %s: %s",
                    attempt,
                    attempts,
                    symbol,
                    e,
                )
            orderbook = None
            if attempt < attempts:
                await asyncio.sleep(2.0 * attempt)

        if orderbook is None:
            # We could not determine the truth. This is the dangerous case: a live
            # order may be resting unmanaged. Escalate loudly rather than assume.
            logger.critical(
                "🚨 [RECONCILE-ORDER] Could not verify order state for %s after %d "
                "attempts. A live order may be resting at the broker.",
                symbol,
                attempts,
            )
            if self.telegram and hasattr(self.telegram, "send_alert"):
                with contextlib.suppress(Exception):
                    await self.telegram.send_alert(
                        f"🚨 *ORDER STATE UNKNOWN*\n\n"
                        f"Symbol: `{symbol}` {side} x{qty}\n"
                        f"Could not read the orderbook after {attempts} attempts.\n\n"
                        f"⚠️ *Check the Fyers app now* — an order may be live and "
                        f"untracked."
                    )
            return None

        try:
            want_side = 1 if side == "BUY" else -1
            cutoff = datetime.now() - timedelta(seconds=lookback_seconds)
            candidates = []

            for o in orderbook.get("orderBook", []):
                if o.get("symbol") != symbol:
                    continue
                if o.get("side") != want_side:
                    continue
                if int(o.get("qty", 0) or 0) != int(qty):
                    continue

                status = FyersOrderStatus.coerce(o.get("status"))
                if status in (FyersOrderStatus.CANCELLED, FyersOrderStatus.REJECTED):
                    continue

                # Prefer recency when the timestamp is parseable; if not, still
                # consider it — a live matching order matters more than its clock.
                ts = o.get("orderDateTime", "")
                recent = True
                for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        recent = datetime.strptime(ts, fmt) >= cutoff
                        break
                    except (ValueError, TypeError):
                        continue
                if recent:
                    candidates.append(o)

            if not candidates:
                logger.info(
                    "[RECONCILE-ORDER] No matching live order for %s %s x%s — "
                    "the timed-out request most likely never reached the exchange.",
                    symbol,
                    side,
                    qty,
                )
                return None

            chosen = candidates[-1]
            order_id = str(chosen.get("id"))
            logger.critical(
                "[RECONCILE-ORDER] Recovered order %s for %s (status=%s)",
                order_id,
                symbol,
                FyersOrderStatus.coerce(chosen.get("status")),
            )
            return order_id

        except Exception as e:
            logger.error("[RECONCILE-ORDER] Parsing orderbook failed for %s: %s", symbol, e)
            return None

    async def _verify_fill_via_rest(self, order_id: str) -> float | None:
        """
        FIX 3: REST fallback when fill timeout fires but cancel returns
        'not a pending order' — means fill arrived but WS event was dropped.
        Returns fill price if confirmed filled, None otherwise.
        """
        try:
            loop = asyncio.get_event_loop()
            rest = getattr(self.broker, "rest_client", None)
            if not rest:
                return None

            async def _fetch_ob():
                return await loop.run_in_executor(None, rest.orderbook)

            try:
                orderbook = await asyncio.wait_for(_fetch_ob(), timeout=ASYNC_RETRIED_TIMEOUT)
            except TimeoutError:
                logger.warning(f"REST verify orderbook timeout for {order_id}")
                return None

            if not isinstance(orderbook, dict) or orderbook.get("s") != "ok":
                return None
            for order in orderbook.get("orderBook", []):
                if str(order.get("id")) == str(order_id):
                    if order.get("status") == FYERS_ORDER_STATUS_TRADED:
                        for key in ("tradedPrice", "tradePrice", "limitPrice"):
                            val = order.get(key, 0)
                            if val:
                                logger.warning(
                                    f"🔍 REST VERIFY: order {order_id} IS FILLED "
                                    f"(WS drop detected) fill_price=₹{val}"
                                )
                                return float(val)
            return None
        except Exception as e:
            logger.error(f"REST fill verify failed for {order_id}: {e}")
            return None

    async def _finalize_closed_position(
        self,
        symbol: str,
        reason: str,
        exit_price: float = 0.0,
        pnl: float = 0.0,
        send_alert: bool = False,
    ) -> None:
        """Shared close-path. Cleans state, releases capital, logs DB."""

        pos = self.active_positions.get(symbol)

        # An unknown result is not a breakeven. exit_price == 0 means no fill price
        # was ever established, and writing that as PNL=0.00% mislabelled four of
        # twelve trades over 7-10 Sep — exactly the ones that failed, which is the
        # information the dataset most needed. An estimated cost basis is excluded
        # for the same reason: its P&L is arithmetic on a price nobody traded at.
        if pos and pos.get("obs_id") and exit_price <= 0:
            logger.warning(
                "[ML] %s closed with no known exit price (%s) — outcome left "
                "UNRESOLVED rather than recorded as breakeven.",
                symbol,
                reason,
            )
        elif pos and pos.get("obs_id") and pos.get("cost_basis_estimated"):
            logger.warning(
                "[ML] %s has an estimated cost basis — outcome not recorded.",
                symbol,
            )
        elif pos and pos.get("obs_id"):
            try:
                outcome = "BREAKEVEN"
                if pnl > 0:
                    outcome = "WIN"
                elif pnl < 0:
                    outcome = "LOSS"

                hold_time = 0
                if pos.get("entry_time"):
                    elapsed = (datetime.now() - pos["entry_time"]).total_seconds()
                    hold_time = int(elapsed / 60)

                # Calculate real pnl_pct based on dollar PNL (works for LONG/SHORT)
                pnl_pct = 0.0
                entry_price = pos.get("entry_price", 0)
                qty = pos.get("qty", 1)
                if entry_price > 0 and qty > 0:
                    pnl_pct = (pnl / (entry_price * qty)) * 100

                # Include MFE/MAE captured by FocusEngine.
                get_ml_logger().update_outcome(
                    obs_id=pos["obs_id"],
                    outcome=outcome,
                    exit_price=exit_price,
                    max_favorable=pos.get("mfe_pct", 0),
                    max_adverse=pos.get("mae_pct", 0),
                    hold_time_mins=hold_time,
                    pnl_pct=pnl_pct,
                )
                logger.info(
                    f"   [ML] Outcome recorded for {symbol} (obs={pos['obs_id']}) "
                    f"MFE={pos.get('mfe_pct', 0):.2f}% MAE={pos.get('mae_pct', 0):.2f}% PNL={pnl_pct:.2f}%"
                )

            except Exception as e:
                logger.error(f"❌ [ML-OUTCOME] Failed for {symbol}: {e}")

        # The async release_slot re-syncs Fyers margin after the close.
        if self.capital:
            try:
                await self.capital.release_slot(broker=self.broker)
            except Exception as e:
                logger.error(f"[CLOSE] Capital release_slot failed for {symbol}: {e}")

        # Prevent reconciliation orphan noise by starting a grace period
        if getattr(self, "trade_manager", None) and getattr(
            self.trade_manager, "reconciliation_engine", None
        ):
            self.trade_manager.reconciliation_engine.mark_recently_closed(symbol)

        if self.db:
            try:
                await self.db.log_trade_exit(
                    symbol,
                    {
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "exit_reason": reason,
                        "status": "CLOSED",
                    },
                )
            except Exception as e:
                logger.error(f"[CLOSE] DB close log failed for {symbol}: {e}")

        # Record outcome in SignalManager for loss tracking
        try:
            pos = self.active_positions.get(symbol)
            if pos:
                if self.trade_manager:
                    self.trade_manager.record_trade_outcome(symbol, pnl)
                else:
                    from shortcircuit.execution.signal_manager import get_signal_manager

                    get_signal_manager().record_outcome(symbol, pnl)
                    logger.info(f"Phase 69 Outcome recorded for {symbol} (direct): ₹{pnl:.2f}")
        except Exception as e:
            logger.error(f"[CLOSE] G13 record failed: {e}")

        self.active_positions.pop(symbol, None)
        self.hard_stops.pop(symbol, None)
        self.exit_in_progress.pop(symbol, None)

        if send_alert and self.telegram and hasattr(self.telegram, "send_alert"):
            with contextlib.suppress(Exception):
                await self.telegram.send_alert(
                    f"🛑 **HARD STOP FILLED**\n\n"
                    f"Symbol: `{symbol}`\n"
                    f"Exit Price: ₹{exit_price:.2f}\n"
                    f"Reason: {reason}"
                )

    async def monitor_hard_stop_status(self, symbol: str) -> bool:
        """
        Detects SL fill from broker orderbook.
        Returns True when hard-stop fill detected and state is closed.
        """
        lock = self._get_lock(symbol)
        async with lock:
            pos = self.active_positions.get(symbol)
            if not pos or pos.get("status") != "OPEN":
                return False

            sl_id = pos.get("sl_id") or self.hard_stops.get(symbol)
            if not sl_id:
                return False

            try:
                orderbook = None
                rest_client = getattr(self.broker, "rest_client", None)
                loop = asyncio.get_event_loop()

                async def _fetch():
                    if rest_client and hasattr(rest_client, "orderbook"):
                        return await loop.run_in_executor(None, rest_client.orderbook)
                    elif hasattr(self.broker, "orderbook"):
                        return await loop.run_in_executor(None, self.broker.orderbook)
                    return None

                try:
                    orderbook = await asyncio.wait_for(_fetch(), timeout=ASYNC_RETRIED_TIMEOUT)
                except TimeoutError:
                    return False

                if not isinstance(orderbook, dict) or orderbook.get("s") != "ok":
                    return False

                # Manual-override detection ("driver's seat")
                # TRANSIT counts as live — an order en route to the exchange is a
                # real resting order, and ignoring it hides genuine manual edits.
                pending_orders = [
                    o
                    for o in orderbook.get("orderBook", [])
                    if o.get("symbol") == symbol and o.get("status") in FYERS_STATUS_WORKING
                ]
                manual_override_detected = False

                ours: set = getattr(self.broker, "bot_order_ids", set())
                for o in pending_orders:
                    # 1. Did the user place a new Limit/Market target order?
                    # An order we placed ourselves is not an override, however
                    # briefly it sits in the book. Comparing against sl_id alone
                    # made our own partial-exit order indistinguishable from the
                    # operator's and stood the bot down mid-scale-out.
                    if str(o.get("id")) != str(sl_id):
                        if str(o.get("id")) in ours:
                            continue
                        manual_override_detected = True
                        break

                    # 2. Did the user drag the Stop Loss line manually?
                    if str(o.get("id")) == str(sl_id):
                        broker_sl = float(o.get("stopPrice", 0))
                        internal_sl = pos.get("stop_loss", 0)
                        if internal_sl > 0 and abs(broker_sl - internal_sl) > 0.06:
                            manual_override_detected = True
                            break

                if manual_override_detected and not pos.get("manual_override"):
                    pos["manual_override"] = True
                    logger.warning(
                        f"⚠️ [MANUAL OVERRIDE] Detected for {symbol}. Bot is backing off."
                    )
                    if self.telegram:
                        await self.telegram.send_alert(
                            f"⚠️ **MANUAL OVERRIDE DETECTED**: `{symbol}`\nBot is backing off. You are now in the driver's seat."
                        )

                for order in orderbook.get("orderBook", []):
                    if str(order.get("id")) != str(sl_id):
                        continue

                    if order.get("status") == FYERS_ORDER_STATUS_TRADED:
                        exit_price = 0.0
                        for price_key in ("tradedPrice", "tradePrice", "limitPrice", "stopPrice"):
                            try:
                                raw = order.get(price_key, 0)
                                if raw:
                                    exit_price = float(raw)
                                    break
                            except Exception:
                                continue

                        logger.warning(
                            f"[HARD_STOP] Filled for {symbol} (sl_id={sl_id}). "
                            "Syncing state/capital/db cleanup."
                        )
                        pnl = 0.0
                        if exit_price > 0:
                            entry_price = pos.get("entry_price", 0)
                            qty = pos.get("qty", 0)
                            if pos["side"] == "SHORT":
                                pnl = (entry_price - exit_price) * qty
                            else:
                                pnl = (exit_price - entry_price) * qty

                        await self._finalize_closed_position(
                            symbol=symbol,
                            reason="HARD_STOP_FILLED",
                            exit_price=exit_price,
                            pnl=pnl,
                            send_alert=True,
                        )
                        return True
                    return False

            except Exception as e:
                logger.error(f"[HARD_STOP] Monitor failed for {symbol}: {e}")

            return False

    async def get_today_trades(self) -> list:
        try:
            positions = await self.broker.get_all_positions()
            trades = []
            for p in positions:
                trades.append(
                    {
                        "symbol": p.get("symbol", "UNKNOWN"),
                        "realised_pnl": float(p.get("realized_profit", 0)),
                        "unrealised_pnl": float(p.get("unrealized_profit", 0)),
                        "qty": p.get("netQty", 0),
                    }
                )
            return trades
        except Exception as e:
            logger.error(f"Error fetching today's trades: {e}")
            return []

    async def startup_reconciliation(self):
        """
        Runs at startup to sync state.
        Also triggers initial capital sync from Fyers.
        """
        import time

        start_time = time.time()
        logger.info("🔍 [STARTUP] Running Async Order Reconciliation...")

        try:
            if self.db:
                try:
                    pool = await self.db.get_pool()
                    async with pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")
                    logger.info("DB Pool warmed up.")
                except Exception as e:
                    logger.warning(f"DB Pool warmup failed: {e}")

            # Initial capital sync from Fyers
            if self.capital:
                await self.capital.sync(self.broker)

            open_positions = await self.broker.get_all_positions()
            for pos in open_positions:
                qty = pos.get("qty", 0)
                symbol = pos.get("symbol")
                if qty != 0:
                    logger.critical(f"⚠️ [STARTUP] ORPHAN FOUND: {symbol} Qty: {qty}")
                    if self.telegram:
                        await self.telegram.send_alert(f"⚠️ **ORPHAN**: {symbol} ({qty})")

            loop = asyncio.get_event_loop()
            await rest_limiter.acquire_async(priority=Priority.HIGH)
            orderbook = await loop.run_in_executor(None, self.broker.rest_client.orderbook)
            if orderbook and isinstance(orderbook, dict) and orderbook.get("s") == "ok":
                pending = [
                    o
                    for o in orderbook.get("orderBook", [])
                    if o.get("status") in FYERS_STATUS_WORKING
                ]
                for order in pending:
                    logger.info(f"[STARTUP] Cancelling stale order {order['id']}")
                    await self.broker.cancel_order(order["id"])

            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > 3000:
                logger.error(f"CRITICAL Slow Reconciliation {elapsed_ms:.0f}ms")
                if self.telegram:
                    await self.telegram.send_alert(f"⚠️ Reconciliation lag {elapsed_ms:.0f}ms")
            elif elapsed_ms > 1500:
                logger.error(f"Slow Reconciliation {elapsed_ms:.0f}ms")
            elif elapsed_ms > 500:
                logger.warning(f"Slow Reconciliation {elapsed_ms:.0f}ms")

            logger.info("✅ [STARTUP] Reconciliation Done.")

        except Exception as e:
            logger.critical(f"🔥 [STARTUP] Failed: {e}")

    # Entry

    async def enter_position(self, signal: dict) -> dict | None:
        """
        Async Entry + SL-M with full capital utilization.

        FIX 1: compute_qty() uses real Fyers margin, not virtual/hardcoded figure.
        FIX 2: acquire_slot() called after confirmed fill (was missing entirely).
        FIX 3: Fill timeout 30s → 15s with REST verification fallback.
        FIX 4: Execution failure cooldown set on any failed entry.
        """
        symbol = signal["symbol"]
        lock = self._get_lock(symbol)

        async with lock:
            logger.info(f"🚀 [ENTRY] Processing {symbol}...")

            # Auto Mode Gate
            if self.telegram and hasattr(self.telegram, "is_auto_mode"):
                if not self.telegram.is_auto_mode():
                    logger.critical(
                        f"🚫 ORDER BLOCKED: enter_position called while auto_mode=False. "
                        f"Signal: {symbol}. This is a bug — focus_engine should have caught this."
                    )
                    return None

            # Sizing via compute_qty (full Fyers margin utilization)
            ltp = signal.get("ltp", 0)
            if ltp == 0:
                ltp = await self.broker.get_ltp(symbol) or 0
            if ltp == 0:
                logger.error(f"❌ [ENTRY] {symbol}: LTP is 0, cannot size position")
                self._set_exec_cooldown(symbol, reason="LTP_ZERO", seconds=300)
                return None

            # There is no local leverage guard: Fyers assigns MIS leverage itself
            # and rejects the order if the symbol does not qualify, which is caught below.

            # Resolved before the branch: the exception handler and the 4x fallback
            # both read this, and it was previously only bound inside the `if`,
            # making it an UnboundLocalError whenever capital was not injected.
            dynamic_leverage = 5.0
            if hasattr(self.broker, "_leverage_cache"):
                dynamic_leverage = self.broker._leverage_cache.get(symbol, 5.0)

            if self.capital:
                qty, required_capital, margin_req = self.capital.compute_qty(
                    symbol, ltp, dynamic_leverage
                )
            else:
                buying_power = 9000.0
                raw_qty = buying_power / ltp
                qty = int(math.floor(raw_qty))
                required_capital = qty * ltp
                margin_req = required_capital / 5.0
                logger.warning(
                    f"[SIZING] Capital manager not injected — using fallback ₹{buying_power}"
                )

            # A spread above 0.4% downgrades to CAUTIOUS execution (reduced size).
            if signal.get("execution_mode") == "CAUTIOUS":
                old_qty = qty
                qty = int(math.floor(qty * 0.5))
                required_capital *= 0.5
                margin_req *= 0.5
                logger.warning(
                    f"⚠️ [CAUTIOUS SIZE] {symbol} qty reduced from {old_qty} to {qty} (50%)"
                )

            # Qty Zero Guard
            if qty == 0:
                real_margin = self.capital._real_margin if self.capital else 0
                msg = (
                    f"🚫 *ORDER BLOCKED — QTY ZERO*\n\n"
                    f"Symbol:  `{symbol}`\n"
                    f"LTP:     ₹{ltp:.2f}\n"
                    f"Margin:  ₹{real_margin:.2f}\n"
                    f"BuyPwr:  ₹{real_margin * 5:.2f}\n\n"
                    f"Stock too expensive for available margin.\n"
                    f"Need ≥ ₹{ltp / 5:.2f} real margin per share."
                )
                logger.warning(f"❌ [ENTRY] {symbol}: qty=0 at ltp=₹{ltp:.2f}")
                if self.telegram and hasattr(self.telegram, "send_alert"):
                    await self.telegram.send_alert(msg)
                self._set_exec_cooldown(symbol, reason="ZERO_QTY", seconds=300)
                return None

            # Read direction from shortcircuit.config runtime switch
            signal_type = config.TRADE_DIRECTION
            side = "SELL" if signal_type == "SHORT" else "BUY"

            logger.info(
                f"[PRE-EXEC] {symbol} {side} qty={qty} @ ₹{ltp:.2f} "
                f"cost=₹{required_capital:.2f} margin_req=₹{margin_req:.2f}"
            )

            # Open the reconciler's grace window BEFORE the order exists. A fill can
            # land at the broker milliseconds after placement and a reconcile cycle
            # can see it before this method has registered anything — which is how
            # NSE:RAYMOND-EQ was adopted as a manual entry 541ms after the bot
            # placed it on 2026-09-08. Claiming the symbol first closes that race.
            self._notify_reconciler(symbol)

            try:
                final_leverage = dynamic_leverage

                # Step 1: Place Entry Order (with 4x Fallback)
                entry_id = None
                try:
                    entry_id = await self.broker.place_order(
                        symbol=symbol, side=side, qty=qty, order_type="MARKET"
                    )
                except OrderPlacementTimeout:
                    # The HTTP call timed out. The order may be LIVE at the exchange.
                    # Blindly retrying here is how you end up double-sized. Reconcile
                    # against the broker before deciding anything.
                    logger.critical(
                        "🚨 [ENTRY] place_order timed out for %s — order state UNKNOWN. "
                        "Reconciling against broker before proceeding.",
                        symbol,
                    )
                    adopted = await self._reconcile_unknown_order(symbol, side, qty)
                    if adopted:
                        entry_id = adopted
                        logger.critical(
                            "[ENTRY] Timed-out order WAS live for %s (id=%s). Adopted.",
                            symbol,
                            entry_id,
                        )
                    else:
                        self._set_exec_cooldown(symbol, reason="PLACE_TIMEOUT", seconds=600)
                        if self.telegram and hasattr(self.telegram, "send_alert"):
                            await self.telegram.send_alert(
                                f"🚨 *ORDER TIMEOUT — VERIFY MANUALLY*\n\n"
                                f"Symbol: `{symbol}` {side} x{qty}\n"
                                f"The place-order call timed out and no matching order "
                                f"was found on the broker.\n"
                                f"⚠️ *Check your Fyers app* — if a position exists, the "
                                f"bot is not tracking it.\n"
                                f"⏳ Cooldown: 10 min"
                            )
                        raise
                except Exception as e:
                    err_str = str(e).lower()
                    is_margin_err = (
                        "margin" in err_str
                        or "insufficient" in err_str
                        or "shortfall" in err_str
                        or "-99" in err_str
                    )
                    if is_margin_err and dynamic_leverage >= 5.0 and self.capital:
                        logger.warning(
                            f"⚠️ Margin rejection at {dynamic_leverage}x for {symbol}. Attempting 4.0x fallback..."
                        )
                        qty, required_capital, margin_req = self.capital.compute_qty(
                            symbol, ltp, 4.0
                        )

                        if qty > 0:
                            entry_id = await self.broker.place_order(
                                symbol=symbol, side=side, qty=qty, order_type="MARKET"
                            )
                            final_leverage = 4.0
                            logger.info(
                                f"✅ Fallback to 4.0x succeeded for {symbol}! (New Qty: {qty})"
                            )
                        else:
                            raise Exception(
                                "Fallback to 4.0x resulted in 0 qty (Insufficient Capital)"
                            )
                    else:
                        raise e  # Rethrow if not a margin error, or if already at 4x

                logger.info(
                    f"✅ Entry Placed: {entry_id} | {symbol} {side} ×{qty} (Lev: {final_leverage}x)"
                )

                if self.telegram and hasattr(self.telegram, "send_alert"):
                    await self.telegram.send_alert(
                        f"✅ *ENTRY ORDER PLACED*\n\n"
                        f"Symbol: `{symbol}` {side}\n"
                        f"Qty: {qty} × ₹{ltp:.2f}\n"
                        f"Cost: ₹{required_capital:.2f}\n"
                        f"Lev: {final_leverage}x\n"
                        f"Order ID: `{entry_id}`"
                    )

                # Wait for fill
                # With the order-socket envelope fixed, this now resolves on the
                # real terminal frame (typically sub-second) instead of always
                # burning the full timeout and being rescued by REST.
                filled = await self.broker.wait_for_fill(entry_id, timeout=15.0)

                if not filled:
                    # VERIFY BEFORE CANCEL. The old order was cancel-first, which
                    # fires a cancel at an order that may have just filled, then
                    # inferred the fill from the cancel's error string. Ask the
                    # orderbook what actually happened first.
                    rest_fill_price = await self._verify_fill_via_rest(entry_id)
                    if rest_fill_price:
                        logger.warning(
                            "[ENTRY] %s filled @ ₹%.2f but no terminal WS frame arrived. "
                            "Proceeding with the fill.",
                            entry_id,
                            rest_fill_price,
                        )
                        filled = True
                        ltp = rest_fill_price  # size/SL off the real fill price
                    else:
                        logger.warning("⚠️ [ENTRY] %s not filled within 15s — cancelling.", entry_id)
                        cancel_result = await self.broker.cancel_order(entry_id)

                        # Cancel can lose a race with a fill. Re-verify before
                        # declaring failure, otherwise we abandon a live position.
                        if not cancel_result:
                            rest_fill_price = await self._verify_fill_via_rest(entry_id)
                            if rest_fill_price:
                                logger.warning(
                                    "[ENTRY] Cancel lost the race — %s filled @ ₹%.2f. "
                                    "Adopting the position.",
                                    entry_id,
                                    rest_fill_price,
                                )
                                filled = True
                                ltp = rest_fill_price

                    if not filled:
                        self._set_exec_cooldown(symbol, reason="FILL_TIMEOUT", seconds=1200)
                        if self.telegram and hasattr(self.telegram, "send_alert"):
                            await self.telegram.send_alert(
                                f"❌ *ENTRY FILL TIMEOUT*\n\n"
                                f"Symbol: `{symbol}`\n"
                                f"Order ID: `{entry_id}`\n"
                                f"Action: Order cancelled, no position taken.\n"
                                f"⏳ Cooldown: 20 min"
                            )
                        return None

                # Use the broker's actual average fill price for SL/TP geometry.
                # Sizing off the pre-trade LTP silently skews every downstream level
                # by the slippage amount.
                actual_fill = await self.broker.get_order_avg_price(entry_id)
                if actual_fill and actual_fill > 0:
                    # Logged for EVERY fill. It used to print only beyond 0.1%, so
                    # the good fills were never recorded and any slippage figure
                    # read back from these lines was biased toward the bad ones.
                    #
                    # "vs signal" is kept for continuity but is NOT a cost: the
                    # signal price is where the setup was spotted, and the move
                    # from there to the trigger is the trade happening. Over 32
                    # fills to 24 Sep it averaged -0.213%, of which -0.094% was that
                    # move; the fill against the trigger was -0.118%. The trigger
                    # figure is the one a backtest should charge.
                    _trig = float(signal.get("gate_trigger") or 0)
                    logger.info(
                        "[ENTRY] %s fill ₹%.2f vs signal ₹%.2f (slippage %.2f%%)%s",
                        symbol,
                        actual_fill,
                        ltp,
                        ((actual_fill - ltp) / ltp) * 100,
                        (
                            f" | vs trigger ₹{_trig:.2f} ({(actual_fill - _trig) / _trig * 100:+.3f}%)"
                            if _trig > 0
                            else ""
                        ),
                    )
                    ltp = actual_fill

                # Acquire the capital slot only AFTER a confirmed fill.
                if self.capital:
                    await self.capital.acquire_slot(symbol)

                # ATR-Based SL
                stop_price = self.compute_stop_loss(ltp, signal)
                sl_side = "BUY" if side == "SELL" else "SELL"

                tick = signal.get("tick_size", 0.05)
                logger.info(
                    f"[SL-CALC] {symbol} ATR-based stop_price=₹{stop_price:.2f} (tick={tick})"
                )

                # Hard gate. compute_stop_loss already re-anchors a wrong-side stop,
                # so reaching here means something is deeply inconsistent — never
                # send an order that is marketable on arrival.
                ok, reason = self.validate_stop_against_fill(symbol, ltp, stop_price, signal_type)
                if not ok:
                    logger.critical(
                        "🚨 [SL-GUARD] Refusing to place stop for %s: %s. "
                        "Exiting position immediately at market.",
                        symbol,
                        reason,
                    )
                    if self.telegram and hasattr(self.telegram, "send_alert"):
                        await self.telegram.send_alert(
                            f"🚨 *UNSAFE STOP — POSITION CLOSED*\n\n"
                            f"Symbol: `{symbol}`\n"
                            f"Entry: ₹{ltp:.2f} | Attempted stop: ₹{stop_price:.2f}\n"
                            f"Reason: {reason}\n\n"
                            f"_A stop on the wrong side of entry fires instantly. "
                            f"Exited at market instead._"
                        )
                    await self._emergency_exit(symbol, qty, "BUY" if side == "SELL" else "SELL")
                    if self.capital:
                        await self.capital.release_slot(broker=self.broker)
                    self._set_exec_cooldown(
                        symbol, reason="UNSAFE_STOP", seconds=EXEC_COOLDOWN_SECONDS
                    )
                    return None

                sl_id, sl_attempts = await self._place_protective_stop(
                    symbol, sl_side, qty, stop_price, tick, signal
                )

                if not sl_id:
                    # Every shape was rejected, including SL-Market. A naked
                    # position is worse than a closed one, so exiting is the last
                    # resort here — not the first response to one rejection.
                    logger.critical(
                        "🚨 [SL-FAIL] %s: every stop placement was rejected: %s",
                        symbol,
                        " | ".join(sl_attempts),
                    )
                    if self.telegram and hasattr(self.telegram, "send_alert"):
                        await self.telegram.send_alert(
                            f"🚨 *SL PLACEMENT FAILED — ALL RETRIES EXHAUSTED*\n\n"
                            f"Symbol: `{symbol}`\n"
                            f"Entry filled @ ₹{ltp:.2f}\n"
                            f"StopPrice attempted: ₹{stop_price:.2f}\n"
                            f"Tried {len(sl_attempts)} order shapes incl. SL-Market.\n"
                            f"Last error: `{(sl_attempts[-1] if sl_attempts else 'unknown')[:150]}`\n"
                            f"⚡ Emergency exit triggered. Capital slot released."
                        )
                    await self._emergency_exit(symbol, qty, sl_side)
                    if self.capital:
                        await self.capital.release_slot(broker=self.broker)
                    self._set_exec_cooldown(
                        symbol, reason="SL_ALL_RETRIES_FAILED", seconds=EXEC_COOLDOWN_SECONDS
                    )
                    return None

                logger.info(f"🛡️ SL Placed: {sl_id} @ ₹{stop_price:.2f}")
                self.hard_stops[symbol] = sl_id

                # Step 4: Register Position
                # 'EOD_HOLD' (TopCoilShort) runs without a take-profit ladder and
                # without the 45-minute time stop, to the 15:10 square-off. Every
                # exit variant that cut the trade shorter scored worse across the
                # sweep: TP1/breakeven/TP2 at a 90-minute cap took the same entries
                # from +0.09% to -0.21% per trade over 206 of them.
                _exit_profile = str(signal.get("exit_profile") or "DEFAULT").upper()
                _eod_hold = _exit_profile == "EOD_HOLD"
                pos_state = {
                    "symbol": symbol,
                    "qty": qty,
                    "side": signal_type,
                    "entry_id": entry_id,
                    "sl_id": sl_id,
                    "status": "OPEN",
                    "entry_time": datetime.now(),
                    "entry_price": ltp,
                    "stop_loss": stop_price,
                    "obs_id": signal.get("obs_id"),  # ML Link
                    "exit_profile": _exit_profile,
                    # G13 Targets for trade_manager monitoring
                    "tp_targets": (None if _eod_hold else self.compute_take_profits(ltp, signal)),
                    "leverage": final_leverage,
                    # Carried so move_hard_stop can round to the SYMBOL's real tick
                    # instead of assuming 0.05 and getting rejected.
                    "tick_size": tick,
                }

                self.active_positions[symbol] = pos_state

                # DB Log
                if self.db:
                    try:
                        await self.db.log_trade_entry(
                            {
                                "symbol": symbol,
                                "direction": side,  # Use 'SELL'/'BUY' from line 490, not 'SHORT'
                                "qty": qty,
                                "entry_price": ltp,
                                "entry_id": entry_id,  # Pass order ID for dedup
                                "leverage": final_leverage,
                            }
                        )
                        # Tells the reconciler this symbol is legitimately ours, and
                        # grants the grace window that stops it adopting our own
                        # order before enter_position has finished registering it.
                        self._notify_reconciler(symbol, dirty=True)
                    except Exception as db_err:
                        # A DB failure must not abort an order that already filled.
                        logger.error(f"❌ [ENTRY-DB] Failed to log entry for {symbol}: {db_err}")

                cap_status = self.capital.get_slot_status() if self.capital else {}
                logger.info(
                    f"✅ [ENTRY COMPLETE] {symbol} {signal_type} ×{qty} @ ₹{ltp:.2f} | "
                    f"SL=₹{stop_price:.2f} | "
                    f"real_margin_used=₹{cap_status.get('real_margin', 0):.2f}"
                )
                return pos_state

            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ [ENTRY] Exception for {symbol}: {error_msg}")

                # Some rejections are permanent for the session, not transient:
                # an "Allowed Basket" refusal means the symbol has no MIS margin
                # that day. Retrying it on a 15-minute cooldown just burns a
                # signal and a rate-limit slot each time.
                _permanent = any(
                    marker in error_msg
                    for marker in ("Allowed Basket", "NSE_MIS_BASKET", "FYERS_RISK_CUG")
                )
                self._set_exec_cooldown(
                    symbol,
                    reason=f"BROKER_EXCEPTION: {error_msg[:50]}",
                    seconds=SESSION_BLOCK_SECONDS if _permanent else EXEC_COOLDOWN_SECONDS,
                )
                if _permanent:
                    logger.warning(
                        "[EXEC] %s blocked for the session: broker RMS rule, not a transient error",
                        symbol,
                    )

                # CRITICAL: Release capital if slot was acquired before this exception
                # (slot is acquired after fill, before SL — so SL exceptions reach here with slot held)
                if self.capital and not self.capital.is_slot_free:
                    try:
                        logger.warning(
                            f"[ENTRY-EXCEPT] Capital slot still occupied during exception "
                            f"for {symbol} — force releasing."
                        )
                        await self.capital.release_slot(broker=self.broker)
                    except Exception as cap_e:
                        logger.error(f"[ENTRY-EXCEPT] Capital release failed: {cap_e}")

                real_margin = self.capital._real_margin if self.capital else 0
                failure_msg = (
                    f"🚨 *ORDER FAILED*\n\n"
                    f"Symbol: `{symbol}` {side}\n"
                    f"Error:  `{error_msg[:200]}`\n\n"
                    f"━━━ Payload ━━━\n"
                    f"Qty:        {qty}\n"
                    f"LTP:        ₹{ltp:.2f}\n"
                    f"Cost:       ₹{required_capital:.2f}\n"
                    f"Margin:     ₹{real_margin:.2f}\n"
                    f"MarginReq:  ₹{margin_req:.2f}\n"
                    f"⏳ Cooldown: 15 min set for {symbol}"
                )
                if self.telegram and hasattr(self.telegram, "send_alert"):
                    await self.telegram.send_alert(failure_msg)
                return None

    # EXIT

    async def verify_position_at_broker(self, symbol: str, attempts: int = 3):
        """
        Ask the broker whether `symbol` is still open. Returns the position dict,
        None if verified flat, or raises PositionFetchError if it cannot tell.

        Retries, because the failure this guards against is transient: a 429 during
        the burst of calls an exit produces. Three tries at 0/0.8/2.0s cost under
        three seconds and covered every failure seen in the 7-10 Sep sessions.
        """
        last_err = None
        for attempt in range(1, attempts + 1):
            try:
                for bp in await self.broker.get_all_positions(force_rest=True):
                    if bp.get("symbol") == symbol and bp.get("qty", 0) != 0:
                        return bp
                return None
            except PositionFetchError as err:
                last_err = err
                logger.warning(
                    "[VERIFY] %s position fetch attempt %d/%d failed: %s",
                    symbol,
                    attempt,
                    attempts,
                    err,
                )
                if attempt < attempts:
                    await asyncio.sleep((0.8, 2.0)[attempt - 1] if attempt <= 2 else 2.0)
        raise PositionFetchError(f"{symbol} unverifiable after {attempts} attempts: {last_err}")

    async def safe_exit(self, symbol: str, reason: str, emergency: bool = False) -> bool:
        """
        Async Safe Exit with WebSocket Race Condition Protection.
        _finalize_closed_position now calls release_slot(broker).
        """
        lock = self._get_lock(symbol)

        async with lock:
            if self.exit_in_progress.get(symbol, False):
                logger.warning(f"EXIT_ALREADY_IN_PROGRESS {symbol}")
                return False

            self.exit_in_progress[symbol] = True

            try:
                if symbol not in self.active_positions:
                    logger.warning(f"[EXIT] {symbol} not found active.")
                    return False

                pos = self.active_positions[symbol]
                if pos["status"] != "OPEN":
                    return False

                logger.info(f"🔻 [EXIT] Initiating Safe Exit for {symbol} ({reason})")

                # Step 0: establish the position's state BEFORE touching its stop.
                # Everything below cancels protection, so an unverifiable position
                # must abort here while it is still covered. Cancelling first and
                # asking afterwards is what left four positions naked on 7-9 Sep.
                try:
                    pos_on_broker = await self.verify_position_at_broker(symbol)
                except PositionFetchError as verify_err:
                    logger.critical(
                        "🚨 [SAFE_EXIT] %s could not be verified at the broker (%s). "
                        "ABORTING the exit with the stop left in place — the position "
                        "stays protected and managed. Exit will be retried.",
                        symbol,
                        verify_err,
                    )
                    pos["status"] = "OPEN"
                    if self.telegram:
                        await self.telegram.send_alert(
                            f"⚠️ *EXIT DEFERRED*\n\n"
                            f"Symbol: `{symbol}`\n"
                            f"Reason: `{reason}`\n\n"
                            f"The broker would not confirm whether this position is "
                            f"still open, so the exit was abandoned rather than "
                            f"cancelling the stop on an unknown position.\n"
                            f"✅ Stop is still in place. Position still tracked."
                        )
                    return False

                # Cancel all pending orders BEFORE placing exit order
                # Prevents phantom SL from executing AFTER position is closed
                try:
                    loop = asyncio.get_event_loop()
                    rest = getattr(self.broker, "rest_client", None)
                    if rest:
                        await rest_limiter.acquire_async(priority=Priority.HIGH)
                        ob = await loop.run_in_executor(None, rest.orderbook)
                        if isinstance(ob, dict) and ob.get("s") == "ok":
                            for o in ob.get("orderBook", []):
                                # Must include TRANSIT: a stop still en route to the
                                # exchange survives this cleanup, then fires AFTER the
                                # position is closed — opening an accidental reverse
                                # position with no bot state behind it.
                                if (
                                    o.get("symbol") == symbol
                                    and o.get("status") in FYERS_STATUS_WORKING
                                ):
                                    await self.broker.cancel_order(o["id"])
                                    logger.info(
                                        f"[SAFE_EXIT] Cancelled resting order {o['id']} for {symbol}"
                                    )
                except Exception as e:
                    logger.warning(f"[SAFE_EXIT] Order cleanup failed (non-fatal): {e}")

                pos["status"] = "CLOSING"

                # Step 1: cancel the SL (best-effort, non-blocking).
                # The SL may already be cancelled/triggered/filled by the exchange.
                # This is expected during fast price action — DO NOT abort exit.
                sl_id = pos.get("sl_id") or self.hard_stops.get(symbol)
                if sl_id:
                    logger.info(f"[EXIT] Cancelling SL {sl_id}...")
                    try:
                        cancelled = await self.broker.cancel_order(sl_id)
                        if cancelled:
                            logger.info(f"✅ SL Cancelled: {sl_id}")
                        else:
                            logger.warning(
                                f"⚠️ SL Cancel returned False for {sl_id} — may already be triggered/cancelled. Continuing exit."
                            )
                    except Exception as sl_cancel_err:
                        logger.warning(
                            f"⚠️ SL Cancel exception for {sl_id}: {sl_cancel_err} — continuing exit anyway."
                        )

                    # Always clean up hard_stops reference
                    if symbol in self.hard_stops:
                        del self.hard_stops[symbol]

                # Step 2: act on the verdict from Step 0. `None` there came from a
                # broker response that actually listed positions, so it is evidence
                # of flat rather than the absence of evidence.
                if pos_on_broker is None:
                    logger.info(
                        f"[SAFE_EXIT] {symbol} already flat on broker (SL/manual close). Finalizing cleanup."
                    )
                    # Try to get actual exit price from the SL order that filled
                    exit_price = 0.0
                    pnl = 0.0
                    if sl_id:
                        with contextlib.suppress(Exception):
                            exit_price = await self.broker.get_order_avg_price(sl_id)
                    if exit_price > 0:
                        entry_price = pos.get("entry_price", 0)
                        qty = pos.get("qty", 0)
                        if pos["side"] == "SHORT":
                            pnl = (entry_price - exit_price) * qty
                        else:
                            pnl = (exit_price - entry_price) * qty

                    await self._finalize_closed_position(
                        symbol=symbol,
                        reason=reason,
                        exit_price=exit_price,
                        pnl=pnl,
                        send_alert=True,
                    )
                    return True

                # Step 3: place the exit order, sized from what the broker says is
                # actually open. Our own count can be stale after a partial, and an
                # exit larger than the position does not close it — it reverses it.
                exit_side = "BUY" if pos["side"] == "SHORT" else "SELL"
                exit_qty = abs(pos_on_broker.get("qty", 0) or 0) or pos["qty"]
                if exit_qty != pos["qty"]:
                    logger.warning(
                        "[SAFE_EXIT] %s internal qty %s vs broker %s — exiting the "
                        "broker's quantity.",
                        symbol,
                        pos["qty"],
                        exit_qty,
                    )
                exit_id = None
                try:
                    exit_id = await self.broker.place_order(
                        symbol=symbol, side=exit_side, qty=exit_qty, order_type="MARKET"
                    )
                    logger.info(f"[EXIT] Exit Order Placed: {exit_id}")
                except Exception as exit_err:
                    logger.error(f"❌ [EXIT] Exit order placement failed: {exit_err}")
                    # Emergency: try once more
                    try:
                        exit_id = await self.broker.place_order(
                            symbol=symbol, side=exit_side, qty=exit_qty, order_type="MARKET"
                        )
                        logger.info(f"[EXIT] Emergency retry succeeded: {exit_id}")
                    except Exception as retry_err:
                        logger.critical(
                            f"🚨 [EXIT] BOTH exit attempts failed for {symbol}: {retry_err}"
                        )
                        # MUST finalize even if exit fails — capital cannot stay locked
                        await self._finalize_closed_position(
                            symbol=symbol,
                            reason=f"{reason}_EXIT_FAILED",
                            exit_price=0.0,
                            pnl=0.0,
                            send_alert=True,
                        )
                        if self.telegram:
                            await self.telegram.send_alert(
                                f"🚨 *EXIT FAILED*\n\n"
                                f"Symbol: `{symbol}`\n"
                                f"Both exit attempts failed.\n"
                                f"⚠️ *CHECK YOUR BROKER APP IMMEDIATELY*\n"
                                f"Capital slot released."
                            )
                        return False

                # Step 4: wait for the fill (15s).
                if exit_id:
                    filled = await self.broker.wait_for_fill(exit_id, timeout=15.0)
                    if filled:
                        logger.info(f"✅ Exit Filled: {symbol}")
                    else:
                        logger.warning(
                            f"⚠️ Exit fill not confirmed via WS for {symbol} — checking REST fallback"
                        )

                # Step 5: cleanup — releases the capital slot and re-syncs margin.
                exit_price = 0.0
                pnl = 0.0
                # Always try to get exit price, even if wait_for_fill timed out
                if exit_id:
                    try:
                        exit_price = await self.broker.get_order_avg_price(exit_id)
                        if exit_price > 0:
                            entry_price = pos.get("entry_price", 0)
                            qty = pos.get("qty", 0)
                            if pos["side"] == "SHORT":
                                pnl = (entry_price - exit_price) * qty
                            else:
                                pnl = (exit_price - entry_price) * qty
                    except Exception as e:
                        logger.warning(f"[SAFE_EXIT] Could not fetch real exit price: {e}")

                await self._finalize_closed_position(
                    symbol=symbol,
                    reason=reason,
                    exit_price=exit_price,
                    pnl=pnl,
                    send_alert=False,
                )
                if self.telegram:
                    pnl_str = f"+₹{pnl:.2f}" if pnl >= 0 else f"-₹{abs(pnl):.2f}"
                    await self.telegram.send_alert(
                        f"✅ **CLOSED**: `{symbol}` ({reason})\n"
                        f"Exit: ₹{exit_price:.2f} | PnL: {pnl_str}"
                    )

                return True

            except Exception as e:
                logger.error(f"❌ [EXIT] Critical Error: {e}")

                # Releasing the slot is only safe once the position is known to be
                # gone. Doing it unconditionally frees the bot to open a second
                # trade against a first one that is still live, and drops the symbol
                # from active_positions — which is what let the reconciler re-adopt
                # a running position as a manual entry on 7 and 9 Sep. Ask first;
                # if it is still open or unanswerable, hold the slot and let the
                # reconciler be the backstop it already is.
                try:
                    still_open = await self.verify_position_at_broker(symbol, attempts=2)
                except PositionFetchError:
                    still_open = self.active_positions.get(symbol)

                if still_open:
                    logger.critical(
                        "🚨 [EXIT] %s crashed mid-exit and is STILL OPEN — keeping the "
                        "capital slot and tracking it rather than abandoning it.",
                        symbol,
                    )
                    if self.telegram:
                        await self.telegram.send_alert(
                            f"🚨 *EXIT ERROR — POSITION STILL OPEN*\n\n"
                            f"Symbol: `{symbol}`\n"
                            f"Error: {str(e)[:100]}\n\n"
                            f"Slot held and position still tracked.\n"
                            f"⚠️ *CHECK YOUR BROKER APP.*"
                        )
                    return False

                # SAFETY NET: Even on crash, try to release capital
                try:
                    await self._finalize_closed_position(
                        symbol=symbol,
                        reason=f"{reason}_CRASH_RECOVERY",
                        exit_price=0.0,
                        pnl=0.0,
                        send_alert=True,
                    )
                    if self.telegram:
                        await self.telegram.send_alert(
                            f"🚨 *EXIT ERROR*: `{symbol}`\n"
                            f"Error: {str(e)[:100]}\n"
                            f"Capital slot released. ⚠️ Check broker app."
                        )
                except Exception as cleanup_err:
                    logger.critical(f"🚨 [EXIT] CLEANUP ALSO FAILED for {symbol}: {cleanup_err}")
                    # Last resort: force release capital
                    if self.capital:
                        with contextlib.suppress(Exception):
                            await self.capital.release_slot(broker=self.broker)
                return False
            finally:
                self.exit_in_progress[symbol] = False

    async def partial_exit(self, symbol: str, exit_qty: int, reason: str) -> bool:
        """
        Closes a portion of the active position.
        Updates internal qty and DB qty.
        Does NOT cancel the SL (that is handled externally by move_hard_stop resizing).
        """
        try:
            pos = self.active_positions.get(symbol)
            if not pos or pos.get("status") != "OPEN":
                logger.warning(
                    f"[PARTIAL_EXIT] {symbol} not OPEN or doesn't exist — skipping stale request."
                )
                return False

            if exit_qty <= 0 or exit_qty >= pos["qty"]:
                logger.warning(
                    f"[PARTIAL_EXIT] Invalid exit_qty {exit_qty} for total {pos.get('qty')}"
                )
                return False

            # Re-check position is still OPEN right before placing the order
            # (guards against race with safe_exit closing the position while we were queued)
            pos2 = self.active_positions.get(symbol)
            if not pos2 or pos2.get("status") != "OPEN":
                logger.warning(f"[PARTIAL_EXIT] {symbol} closed while queued — aborting.")
                return False

            logger.info(f"🔻 [PARTIAL_EXIT] Closing {exit_qty} shares of {symbol} ({reason})")

            exit_side = "BUY" if pos["side"] == "SHORT" else "SELL"
            exit_id = await self.broker.place_order(
                symbol=symbol, side=exit_side, qty=exit_qty, order_type="MARKET"
            )

            if not exit_id:
                logger.error(f"❌ [PARTIAL_EXIT] Placement failed for {symbol}")
                return False

            # Wait for fill
            filled = await self.broker.wait_for_fill(exit_id, timeout=10.0)
            if filled:
                logger.info(f"✅ Partial Exit Filled: {symbol} ({exit_qty} qty)")
            else:
                logger.warning(
                    f"⚠️ Partial Exit fill not confirmed via WS for {symbol} — checking REST fallback"
                )

            # Try to get exit price for DB logic
            exit_price = 0.0
            pnl = 0.0
            try:
                exit_price = await self.broker.get_order_avg_price(exit_id)
                if exit_price > 0:
                    entry_price = pos.get("entry_price", 0)
                    if pos["side"] == "SHORT":
                        pnl = (entry_price - exit_price) * exit_qty
                    else:
                        pnl = (exit_price - entry_price) * exit_qty
            except Exception as e:
                logger.warning(f"[PARTIAL_EXIT] Could not fetch avg price: {e}")

            # Update DB
            if self.db:
                try:
                    await self.db.execute(
                        "UPDATE positions SET qty = qty - $1 WHERE symbol = $2 AND session_date = CURRENT_DATE AND state = 'OPEN'",
                        exit_qty,
                        symbol,
                    )
                except Exception as db_err:
                    logger.error(f"[PARTIAL_EXIT] DB qty update failed: {db_err}")

            # Update internal state
            pos["qty"] -= exit_qty

            self._notify_reconciler(symbol, dirty=True)

            if self.telegram:
                pnl_str = f"+₹{pnl:.2f}" if pnl >= 0 else f"-₹{abs(pnl):.2f}"
                await self.telegram.send_alert(
                    f"✂️ **PARTIAL CLOSE**: `{symbol}` ({reason})\n"
                    f"Qty: {exit_qty} | Exit: ₹{exit_price:.2f} | PnL: {pnl_str}"
                )

            return True

        except Exception as e:
            logger.error(f"❌ [PARTIAL_EXIT] Exception for {symbol}: {e}")
            return False

    async def move_hard_stop(
        self, symbol: str, new_stop_price: float, new_qty: int | None = None
    ) -> bool:
        """
        Move the broker-side SL-M order to a new stop price (e.g. for BE activation).
        Optionally resizes the SL order if new_qty is provided (for partial exits).
        Strategy: Modify the existing SL-M order to the new stop price and/or qty.
        Falls back to cancel+replace if modify is not supported.
        Returns True if broker SL is now modified, False otherwise.
        """
        try:
            pos = self.active_positions.get(symbol)
            if not pos or pos.get("status") != "OPEN":
                logger.warning(
                    f"[MOVE_SL] {symbol} not OPEN or not in active_positions — skipping stale request."
                )
                return False

            sl_id = pos.get("sl_id") or self.hard_stops.get(symbol)
            if not sl_id:
                logger.warning(f"[MOVE_SL] No sl_id found for {symbol}")
                return False

            loop = asyncio.get_event_loop()
            rest = getattr(self.broker, "rest_client", None)
            if not rest:
                logger.error(f"[MOVE_SL] No rest_client for {symbol}")
                return False

            # Get current SL order details to preserve qty if new_qty is not provided.
            # Throttled: this used to race the partial exit it follows, and both calls
            # landed on Fyers inside the same millisecond. The orderbook lost, came
            # back 429, and the stop was never resized — see the 1 Sep ENGINERSIN flip.
            await rest_limiter.acquire_async(priority=Priority.HIGH)
            orderbook = await loop.run_in_executor(None, rest.orderbook)
            if not isinstance(orderbook, dict) or orderbook.get("s") != "ok":
                logger.error(
                    "[MOVE_SL] Orderbook fetch failed for %s: %s",
                    symbol,
                    orderbook if isinstance(orderbook, dict) else type(orderbook).__name__,
                )
                return False

            current_sl_order = None
            for order in orderbook.get("orderBook", []):
                if (
                    str(order.get("id")) == str(sl_id)
                    and order.get("status") in FYERS_STATUS_WORKING
                ):
                    current_sl_order = order
                    break

            if not current_sl_order:
                logger.warning(
                    f"[MOVE_SL] SL order {sl_id} not found as pending for {symbol} — may already be filled"
                )
                return False

            qty = new_qty if new_qty is not None else current_sl_order.get("qty", pos.get("qty", 0))
            direction = pos.get("side", "SHORT")

            # Use the SYMBOL'S real tick, not a hardcoded 0.05. NSE ticks are
            # 0.01/0.05/0.10 depending on the scrip; rounding a 0.01-tick stock to
            # 0.05 produces a price the exchange rejects, so the breakeven stop
            # silently never moves.
            tick = pos.get("tick_size") or 0.05

            # Match the entry SL's 2% limit buffer. The previous 0.5% buffer meant a
            # BE stop could gap straight through its own limit in a fast move and
            # never fill — the exact scenario a breakeven stop exists to prevent.
            buffer_pct = 0.02
            if direction == "SHORT":
                raw_limit = new_stop_price * (1 + buffer_pct)
                stop_rounded = math.ceil(new_stop_price / tick) * tick
            else:
                raw_limit = new_stop_price * (1 - buffer_pct)
                stop_rounded = math.floor(new_stop_price / tick) * tick

            limit_price = round(round(raw_limit / tick) * tick, 2)
            stop_rounded = round(stop_rounded, 2)

            # type must match the order actually resting at the broker. Entry places
            # SL_LIMIT (Fyers type 4); sending type 3 here would be a different
            # instrument and gets rejected.
            modify_data = {
                "id": sl_id,
                "qty": qty,
                "type": 4,  # SL-Limit — same as placed at entry
                "limitPrice": limit_price,
                "stopPrice": stop_rounded,
            }

            await rest_limiter.acquire_async(priority=Priority.HIGH)
            resp = await loop.run_in_executor(None, lambda: rest.modify_order(data=modify_data))

            if resp and resp.get("s") == "ok":
                # Update our internal state to reflect the new SL
                pos["stop_loss"] = new_stop_price
                logger.info(
                    "✅ [MOVE_SL] %s broker SL moved → ₹%.2f qty=%s (order %s)",
                    symbol,
                    new_stop_price,
                    qty,
                    sl_id,
                )
                return True
            else:
                logger.error(f"❌ [MOVE_SL] modify_order failed for {symbol}: {resp}")
                return False

        except Exception as e:
            logger.error(f"[MOVE_SL] Exception for {symbol}: {e}")
            return False

    async def verify_stop_qty(self, symbol: str) -> int | None:
        """Quantity of the stop actually resting at the broker, or None if unknown.

        A modify returning 's': 'ok' is the broker accepting the request, not proof
        the resting order changed. The invariant that matters — a stop must never be
        larger than the position it protects — is only worth asserting against what
        the orderbook really says.
        """
        try:
            pos = self.active_positions.get(symbol)
            sl_id = (pos or {}).get("sl_order_id")
            rest = getattr(self.broker, "rest_client", None)
            if not sl_id or not rest:
                return None
            await rest_limiter.acquire_async(priority=Priority.HIGH)
            loop = asyncio.get_event_loop()
            book = await loop.run_in_executor(None, rest.orderbook)
            if not isinstance(book, dict) or book.get("s") != "ok":
                logger.warning("[VERIFY_SL] orderbook unavailable for %s: %s", symbol, book)
                return None
            for order in book.get("orderBook", []):
                if (
                    str(order.get("id")) == str(sl_id)
                    and order.get("status") in FYERS_STATUS_WORKING
                ):
                    return int(order.get("qty") or 0)
            return 0  # no working stop found — nothing is resting
        except Exception as e:
            logger.warning("[VERIFY_SL] %s: %s", symbol, e)
            return None

    async def _place_protective_stop(
        self,
        symbol: str,
        sl_side: str,
        qty: int,
        stop_price: float,
        tick: float,
        signal: dict | None = None,
    ):
        """
        Place the broker-side stop, escalating through progressively safer order
        shapes instead of abandoning the position on the first rejection.

        BUG-2026-08-12: NSE:ELLEN-EQ was force-closed at a loss because a single
        SL-Limit attempt was rejected. The stop itself (₹325.10) was perfectly
        valid — it was the 2% limit buffer that put the *limit* price at ₹331.60,
        outside the symbol's circuit band. The broker's error quoted that exact
        number. One rejection, position gone.

        The ladder, in order of preference:
          1-3. SL_LIMIT with shrinking buffers, clamped to the circuit band when
               the signal carries one. A tighter buffer risks the limit not
               filling in a fast move, which is why it is not the first choice.
          4.   SL_MARKET (Fyers type 3). It carries no limit price at all, so it
               cannot breach a circuit band. Fills are not price-guaranteed,
               which is an acceptable trade for being protected at all.

        Returns (order_id, attempt_log). order_id is None only if every shape
        failed, which is the one case where the caller should exit the position.
        """
        upper = float((signal or {}).get("upper_circuit") or 0.0)
        lower = float((signal or {}).get("lower_circuit") or 0.0)
        attempts: list = []

        for buffer_pct in (0.02, 0.01, 0.003):
            if sl_side == "BUY":
                limit_price = stop_price * (1 + buffer_pct)
                if upper > 0:
                    limit_price = min(limit_price, upper)
            else:
                limit_price = stop_price * (1 - buffer_pct)
                if lower > 0:
                    limit_price = max(limit_price, lower)
            limit_price = round(round(limit_price / tick) * tick, 2)

            try:
                sl_id = await self.broker.place_order(
                    symbol=symbol,
                    side=sl_side,
                    qty=qty,
                    order_type="SL_LIMIT",
                    price=limit_price,
                    trigger_price=stop_price,
                )
                if sl_id:
                    if attempts:
                        logger.warning(
                            "[SL-RETRY] %s stop placed on attempt %d "
                            "(buffer %.1f%%, limit ₹%.2f) after %d rejection(s)",
                            symbol,
                            len(attempts) + 1,
                            buffer_pct * 100,
                            limit_price,
                            len(attempts),
                        )
                    return sl_id, attempts
                attempts.append(
                    f"SL_LIMIT buf={buffer_pct:.1%} limit=₹{limit_price:.2f}: no order id"
                )
            except Exception as exc:
                attempts.append(
                    f"SL_LIMIT buf={buffer_pct:.1%} limit=₹{limit_price:.2f}: {str(exc)[:120]}"
                )
            logger.warning("[SL-RETRY] %s attempt failed: %s", symbol, attempts[-1])

        # No limit price, so no circuit band to breach.
        try:
            sl_id = await self.broker.place_order(
                symbol=symbol,
                side=sl_side,
                qty=qty,
                order_type="SL_MARKET",
                trigger_price=stop_price,
            )
            if sl_id:
                logger.warning(
                    "[SL-RETRY] %s protected by SL_MARKET after %d SL_LIMIT rejection(s)",
                    symbol,
                    len(attempts),
                )
                return sl_id, attempts
            attempts.append("SL_MARKET: no order id")
        except Exception as exc:
            attempts.append(f"SL_MARKET: {str(exc)[:120]}")
        logger.critical("[SL-RETRY] %s SL_MARKET also failed: %s", symbol, attempts[-1])

        return None, attempts

    async def _emergency_exit(self, symbol: str, qty: int, side: str):
        try:
            await self.broker.place_order(symbol=symbol, qty=qty, side=side, order_type="MARKET")
        except Exception as e:
            logger.critical(f"EMERGENCY EXIT FAILED: {e}")
