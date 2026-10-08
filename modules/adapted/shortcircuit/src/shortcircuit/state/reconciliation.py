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


import asyncio
import json
import logging
import math
import re
import time
from datetime import date, datetime
from datetime import time as dtime

from shortcircuit.broker.fyers_broker_interface import FyersBrokerInterface
from shortcircuit.broker.fyers_connect import ASYNC_RETRIED_TIMEOUT
from shortcircuit.broker.rest_limiter import Priority, rest_limiter
from shortcircuit.state.database import DatabaseManager

logger = logging.getLogger(__name__)
FORCE_REST_SYNC_INTERVAL = 300  # 5 minutes


# Tick sizes learned from the broker's own rejection messages, per session.
# NSE revised its tick bands in April 2025 and the position payload does not
# carry a tick size, so guessing is not viable — but a rejection states the
# exact value, which makes this self-correcting after one failed attempt.
_LEARNED_TICKS: dict = {}
_TICK_SIZE_RE = re.compile(r"tick\s*size\s*([0-9]*\.?[0-9]+)", re.I)


def learn_tick_from_error(symbol: str, error: str):
    """Extract the true tick size from a broker rejection and remember it."""
    m = _TICK_SIZE_RE.search(str(error or ""))
    if not m:
        return None
    try:
        tick = float(m.group(1))
    except ValueError:
        return None
    if tick <= 0:
        return None
    _LEARNED_TICKS[symbol] = tick
    logger.warning("[TICK] learned %s tick=%.4f from broker rejection", symbol, tick)
    return tick


def round_stop_away_from_entry(raw: float, tick: float, side: str) -> float:
    """Round a stop away from the position, so rounding never tightens it."""
    if tick <= 0:
        tick = 0.05
    if side == "SHORT":
        return round(math.ceil(raw / tick) * tick, 2)
    return round(math.floor(raw / tick) * tick, 2)


class ReconciliationEngine:
    """
    HFT Reconciliation Engine — Zero-cost when flat, cache-driven when live.

    Architecture:
    - FLAT STATE  → pure cache check, 0 REST calls, 0 DB queries. Sub-millisecond.
    - LIVE STATE  → cache-first broker read, DB read with dirty-flag guard.
    - Dirty flag  → set externally by TradeManager on open/close events.
    """

    def __init__(
        self,
        broker: FyersBrokerInterface,
        db_manager: DatabaseManager,
        telegram_bot,
        capital_manager=None,
        order_manager=None,
    ):
        self.broker = broker
        self.db = db_manager
        self.telegram = telegram_bot
        self.capital = capital_manager
        self.order_manager = order_manager
        self.running = False

        # Internal State Cache
        self._db_positions: dict = {}
        self._db_dirty: bool = True
        self._has_open_positions: bool = False
        self._shutdown_event: asyncio.Event = None
        self._last_rest_sync: float = 0.0
        self._recently_closed: dict = {}  # symbol → close_timestamp (grace period)
        self._recently_modified: dict = {}  # symbol → timestamp (grace period for entry/partial exit)
        self._orphan_grace_secs: float = 30.0  # Ignore orphans for 30s after internal close

        # Adoption bookkeeping. A manually-entered position is adopted ONCE.
        # symbol -> {'sl_id', 'qty', 'adopted_at', 'naked_alerted_at'}
        # Without this, NSE:TIINDIA-EQ was re-adopted three times on 18 Aug and
        # a fresh emergency stop was attempted each time. The operator is
        # entitled to manage their own stop; the bot must not fight them for it.
        self._adoptions: dict = {}
        self._naked_alert_cooldown: float = 900.0  # re-warn at most every 15 min

    # Called by TradeManager when trade opens or closes
    def mark_dirty(self):
        """
        Call this from TradeManager whenever a trade opens or closes.
        Forces DB re-fetch on next reconciliation cycle.
        """
        self._db_dirty = True

    def mark_recently_closed(self, symbol: str):
        """
        Record that a position was just closed internally.
        Prevents false orphan alerts during broker settlement lag.
        """
        import time

        self._recently_closed[symbol] = time.time()
        logger.debug(f"[RECONCILE] {symbol} marked recently closed — grace period active")
        logger.debug("🔁 Reconciliation marked dirty.")

    def mark_recently_modified(self, symbol: str):
        """
        Record that a position was just entered or partially exited.
        Suppresses orphan/mismatch spam during DB ↔ broker sync lag.
        """
        import time

        self._recently_modified[symbol] = time.time()
        logger.debug(f"[RECONCILE] {symbol} marked recently modified — grace period active")

    async def _classify_exit(self, sym: str, pos: dict):
        """
        Work out *why* a position disappeared, from evidence rather than assumption.

        BUG-2026-08-12: NSE:TARSONS-EQ was reported as a manual close with "PnL
        for this trade not tracked". The log shows the bot had watched its own
        emergency stop fill:

            [ADOPT] Emergency SL placed: sl_id=26081200125796 | stop=₹326.40
            💹 TRADE | BUY 10 NSE:TARSONS-EQ @ ₹327.2 | order=26081200125796
            Order 26081200125796: FILLED ✅ | price=₹327.20

        It held the order id, saw the fill and knew the price, then discarded all
        of it. Every exit that follows is classified from what is observable:

          SL_HIT          the tracked stop order reached a fill
          EOD_SQUAREOFF   position vanished at or after the 15:10 deadline
          MANUAL_TP_EXIT  operator closed it, and the close was favourable
          MANUAL_EXIT     operator closed it, and it was not

        Returns (reason, exit_price, pnl). PnL is always computed when entry,
        quantity and an exit price are known — "not tracked" is not an outcome.
        """
        import shortcircuit.config as _cfg
        from shortcircuit.broker.fyers_broker_interface import FyersOrderStatus

        entry = float(pos.get("entry_price") or 0.0)
        qty = int(pos.get("qty") or 0)
        direction = str(pos.get("side") or getattr(_cfg, "TRADE_DIRECTION", "SHORT")).upper()

        exit_price = 0.0
        reason = None

        # 1. Did our own stop fill? Strongest evidence available, so checked first.
        sl_id = self.order_manager.hard_stops.get(sym) if self.order_manager else None
        if sl_id:
            try:
                cached = getattr(self.broker, "order_status_cache", {}).get(str(sl_id))
                is_filled = cached is not None and int(getattr(cached, "status", 0)) == int(
                    FyersOrderStatus.FILLED
                )
                avg = await self.broker.get_order_avg_price(sl_id)
                if is_filled or (avg and avg > 0):
                    exit_price = float(avg or 0.0)
                    reason = "SL_HIT"
                    logger.info(
                        "[EXIT-CLASSIFY] %s stop order %s filled @ ₹%.2f — this was a stop hit, "
                        "not a manual exit",
                        sym,
                        sl_id,
                        exit_price,
                    )
            except Exception as exc:
                logger.warning("[EXIT-CLASSIFY] %s could not read stop %s: %s", sym, sl_id, exc)

        # 2. Past the square-off deadline the scheduler is the likely closer.
        if reason is None:
            try:
                from shortcircuit.eod.eod_scheduler import EOD_TIME

                if datetime.now(pytz.timezone("Asia/Kolkata")).time() >= EOD_TIME:
                    reason = "EOD_SQUAREOFF"
            except Exception:
                pass

        if exit_price <= 0:
            try:
                exit_price = float(await self.broker.get_ltp(sym) or 0.0)
            except Exception:
                exit_price = 0.0

        pnl = 0.0
        if entry > 0 and qty > 0 and exit_price > 0:
            pnl = (
                ((exit_price - entry) * qty)
                if direction == "LONG"
                else ((entry - exit_price) * qty)
            )

        # 3. Nothing else explains it, so the operator closed it. Which way it went
        #    is the only thing distinguishing a taken profit from a bail-out.
        if reason is None:
            reason = "MANUAL_TP_EXIT" if pnl > 0 else "MANUAL_EXIT"

        return reason, exit_price, pnl

    EXIT_LABELS = {
        "SL_HIT": "🛑 *STOP-LOSS FILLED*",
        "EOD_SQUAREOFF": "🌆 *EOD SQUARE-OFF*",
        "MANUAL_TP_EXIT": "💰 *MANUAL PROFIT EXIT*",
        "MANUAL_EXIT": "👻 *MANUAL EXIT*",
    }

    async def start(self):
        if self.running:
            return
        asyncio.create_task(self.run())

    async def stop(self):
        """Stop with hard timeout — never hangs more than 10s."""
        self.running = False
        logger.info("[REC-ENGINE] Stop called. Hard timeout: 10s.")
        # Nothing to await currently — stop is immediate once running=False
        logger.info("🛑 Reconciliation Engine Stopped.")

    async def _interruptible_sleep(self, seconds: float):
        """Sleep that wakes immediately when shutdown_event is set."""
        if self._shutdown_event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=seconds)
        except TimeoutError:
            pass  # Normal — sleep completed without shutdown

    async def run(self, shutdown_event: asyncio.Event = None):
        if self.running:
            return
        self.running = True
        self._shutdown_event = shutdown_event
        logger.info("✅ Reconciliation Engine Started (WebSocket Mode).")
        while self.running and (shutdown_event is None or not shutdown_event.is_set()):
            start_time = asyncio.get_event_loop().time()
            try:
                await self.reconcile()
            except Exception as e:
                logger.error(f"Reconciliation error: {e}")

            elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            interval = self._get_reconciliation_interval()

            if elapsed_ms > 500 and self._is_market_hours():
                logger.warning(f"⚠️ Slow Reconciliation: {elapsed_ms:.3f}ms")
            elif elapsed_ms > 3000:
                logger.warning(f"⚠️ Very Slow Reconciliation (off-hours): {elapsed_ms:.3f}ms")

            await self._interruptible_sleep(interval)

    async def reconcile(self):
        """
        One reconciliation pass.

        FAST PATH (flat):
            - Read broker WebSocket cache directly (0 REST, 0 DB)
            - If cache also shows flat → return immediately
            - Total cost: ~0.1ms

        LIVE PATH (positions open):
            - Broker: WebSocket cache first, REST fallback only if cache is stale
            - DB: only re-query if dirty flag is set
            - Full compare + alert on divergence
        """

        # Step 1: read the broker cache directly (zero cost).
        broker_open = self._read_broker_cache()

        # Step 1.5: periodic forced REST sync.
        # Guarantee recovery even if WS cache/DB flags fail
        loop = asyncio.get_event_loop()
        now = loop.time()
        force_live = (now - self._last_rest_sync) > FORCE_REST_SYNC_INTERVAL

        # FAST PATH: Both sides flat
        if (
            not force_live
            and not broker_open
            and not self._has_open_positions
            and not self._db_dirty
        ):
            # Nothing on broker, nothing tracked locally, no recent updates → definitively flat
            return

        if force_live:
            logger.info("📡 [REC] Periodic Force REST Sync triggered (5-min safety).")
            self._last_rest_sync = now

        # Live path
        # Broker has positions OR we think DB has positions

        # Step 2: Get broker positions (cache-first, REST fallback)
        broker_positions = {}
        broker_fetch_failed = False
        try:
            broker_positions = await self._get_broker_positions_cached(broker_open)
        except Exception as e:
            # Do NOT let a failed fetch look like "broker is flat". An empty
            # broker_positions makes every DB row a phantom, and phantom handling
            # force-closes DB state and releases capital. A degraded API must never
            # be able to trigger that.
            broker_fetch_failed = True
            logger.error(f"Reconcile: Broker fetch failed (API degraded): {e}")

        # Step 3: Get DB positions (only if dirty)
        try:
            db_positions = await self._get_db_positions_cached()
        except Exception as e:
            logger.error(f"Reconcile: DB fetch failed: {e}")
            return

        # Update master flat/live flag
        self._has_open_positions = bool(db_positions) or bool(broker_positions)

        # Step 4: Compare
        orphans = []
        phantoms = []
        mismatched = []

        for symbol, b_pos in broker_positions.items():
            # 'qty' is now normalised to absolute; 'net_qty' keeps the sign so the
            # long/short side can still be inferred downstream by adopt_orphan.
            b_qty_abs = abs(b_pos.get("qty", 0) or 0)
            b_qty = b_pos.get("net_qty", b_qty_abs)
            if symbol not in db_positions:
                # Grace period — skip orphan alert if recently closed internally
                import time

                closed_at = self._recently_closed.get(symbol, 0)
                if time.time() - closed_at < self._orphan_grace_secs:
                    logger.debug(
                        f"[RECONCILE] Suppressed orphan for {symbol} — "
                        f"closed {time.time() - closed_at:.1f}s ago (grace={self._orphan_grace_secs}s)"
                    )
                    continue
                # Also suppress if recently modified (just entered / partial exit)
                modified_at = self._recently_modified.get(symbol, 0)
                if time.time() - modified_at < self._orphan_grace_secs:
                    logger.debug(
                        f"[RECONCILE] Suppressed orphan for {symbol} — "
                        f"modified {time.time() - modified_at:.1f}s ago (grace={self._orphan_grace_secs}s)"
                    )
                    continue
                # Clean up expired grace entries
                self._recently_closed = {
                    s: t
                    for s, t in self._recently_closed.items()
                    if time.time() - t < self._orphan_grace_secs
                }
                self._recently_modified = {
                    s: t
                    for s, t in self._recently_modified.items()
                    if time.time() - t < self._orphan_grace_secs
                }
                orphans.append({"symbol": symbol, "qty": b_qty_abs, "net_qty": b_qty})
            elif db_positions[symbol] != b_qty_abs:
                # Suppress mismatch if recently modified (partial exit in progress)
                import time

                modified_at = self._recently_modified.get(symbol, 0)
                if time.time() - modified_at < self._orphan_grace_secs:
                    logger.debug(
                        f"[RECONCILE] Suppressed mismatch for {symbol} — "
                        f"modified {time.time() - modified_at:.1f}s ago"
                    )
                    continue
                mismatched.append(
                    {"symbol": symbol, "db_qty": db_positions[symbol], "broker_qty": b_qty_abs}
                )

        for symbol, db_qty in db_positions.items():
            if symbol not in broker_positions:
                # A position the bot itself just closed is still in the cached DB
                # snapshot for a few seconds. That is lag, not a vanished position:
                # on 29 Sep NSE:FERMENTA-EQ's own stop fill was booked, then 0.6s
                # later raised a CRITICAL "POSITION VANISHED" and a second Telegram
                # close alert. The grace period only ever covered orphans.
                import time

                closed_at = self._recently_closed.get(symbol, 0)
                still_tracked = bool(
                    self.order_manager
                    and symbol in getattr(self.order_manager, "active_positions", {})
                )
                if time.time() - closed_at < self._orphan_grace_secs and not still_tracked:
                    logger.debug(
                        f"[RECONCILE] Suppressed phantom for {symbol} — closed "
                        f"{time.time() - closed_at:.1f}s ago; refreshing the DB snapshot"
                    )
                    self._db_dirty = True
                    continue
                phantoms.append({"symbol": symbol, "qty": db_qty})

        # Step 5: Act on divergence — only when the broker view is trustworthy.
        if orphans or phantoms or mismatched:
            if broker_fetch_failed:
                logger.warning(
                    "⚠️ Skipping divergence handling — broker fetch failed, so an "
                    "empty position set proves nothing. Deferring to next cycle."
                )
            elif not broker_positions and broker_open:
                # Cache says positions exist but the map came back empty: contradictory.
                logger.warning(
                    "⚠️ Skipping divergence handling — cache reports open positions "
                    "but the position map is empty (inconsistent view)."
                )
            else:
                await self._handle_divergence(
                    db_positions, broker_positions, orphans, phantoms, mismatched
                )

    # Private Helpers

    def _read_broker_cache(self) -> bool:
        """
        Read broker WebSocket position cache directly.
        Returns True if any non-zero qty position exists.
        Zero REST calls. Zero DB calls. ~0.1ms.
        """
        try:
            if not self.broker.position_cache:
                return False
            return any(p.net_qty != 0 for p in self.broker.position_cache.values())
        except Exception:
            return False  # if cache is broken, fall through to live path

    async def _get_broker_positions_cached(self, cache_has_data: bool) -> dict:
        """
        Build the broker-side position map.

        The websocket cache is now genuinely populated, so this is a zero-REST read
        whenever the socket is healthy. Falls back to REST when the cache is empty,
        because an empty cache means "no events yet", not "flat".

        Two bugs fixed here:
          * `qty` was populated from p.net_qty, which is SIGNED. Downstream compares
            it against the DB's absolute quantity, so every short reported a
            spurious quantity mismatch.
          * The REST fallback ran get_all_positions() inside a brand-new event loop
            spun up in an executor thread — from async code that could simply await
            it. That loop churn was pure overhead, and its 2s timeout was shorter
            than the inner call's own 10s timeout, so it almost always fired first.
        """
        if cache_has_data:
            result = {}
            with self.broker._position_cache_lock:
                snapshot = list(self.broker.position_cache.items())
            for symbol, p in snapshot:
                if p.net_qty != 0:
                    result[symbol] = {
                        "symbol": symbol,
                        "qty": abs(p.net_qty),  # absolute, matches DB
                        "net_qty": p.net_qty,  # signed, for side inference
                        "avg_price": getattr(p, "avg_price", 0.0),
                    }
            return result

        # Cache empty — verify against REST rather than assuming flat.
        try:
            positions = await asyncio.wait_for(
                self.broker.get_all_positions(force_rest=True), timeout=ASYNC_RETRIED_TIMEOUT
            )
        except TimeoutError:
            logger.warning(
                "[RECONCILE] Broker position fetch timed out — treating as UNKNOWN, "
                "not flat. Skipping this cycle's divergence check."
            )
            raise

        return {
            p["symbol"]: {
                "symbol": p["symbol"],
                "qty": p.get("qty", 0),
                "net_qty": p.get("netQty", 0),
                "avg_price": p.get("avgPrice", 0.0),
            }
            for p in positions
            if p.get("symbol")
        }

    async def _get_db_positions_cached(self) -> dict:
        """
        Return cached DB positions unless dirty flag is set.
        DB query only runs when TradeManager signals a change.
        """
        if not self._db_dirty:
            return self._db_positions  # cache hit — 0ms

        # Cache miss — re-fetch
        rows = await asyncio.wait_for(
            self.db.fetch("SELECT symbol, qty FROM positions WHERE state = 'OPEN'"), timeout=1.5
        )
        self._db_positions = {row["symbol"]: row["qty"] for row in rows}
        self._db_dirty = False  # clear flag until next trade event
        logger.debug(f"🗄️ DB positions refreshed: {len(self._db_positions)} open.")
        return self._db_positions

    async def _find_live_protective_order(self, symbol: str, sl_side: str):
        """
        Return the id of a live stop already protecting `symbol`, or None.

        The operator is entitled to run their own stop, move it, or replace ours.
        This is what stops the bot fighting them: before placing an emergency
        stop it asks the broker whether the position is already covered, and by
        whom it does not care.

        Fyers status 6 = PENDING, 4 = TRANSIT — both are live. A stop that has
        already filled or been cancelled protects nothing and is ignored.
        """
        try:
            client = getattr(self.broker, "rest_client", None) or getattr(
                self.broker, "fyers", None
            )
            if client is None:
                return None
            await rest_limiter.acquire_async(priority=Priority.HIGH)
            book = await asyncio.to_thread(client.orderbook)
            orders = (book or {}).get("orderBook") or []
        except Exception as exc:
            # Fail open: not knowing is not evidence of protection. Placing a
            # duplicate stop is recoverable; leaving a position naked is not.
            logger.warning("[ADOPT] could not read orderbook for %s: %s", symbol, exc)
            return None

        for o in orders:
            try:
                if o.get("symbol") != symbol:
                    continue
                if int(o.get("status", 0)) not in (4, 6):  # TRANSIT / PENDING
                    continue
                # side is -1 SELL / 1 BUY in Fyers; a protective order for a
                # short is a BUY, and vice versa.
                want = 1 if sl_side == "BUY" else -1
                if int(o.get("side", 0)) != want:
                    continue
                # type 3 = SL-Market, 4 = SL-Limit. A plain limit order sitting
                # in the book is a target, not a stop, and must not be mistaken
                # for protection.
                if int(o.get("type", 0)) not in (3, 4):
                    continue
                return str(o.get("id"))
            except (TypeError, ValueError):
                continue
        return None

    def forget_adoption(self, symbol: str):
        """Clear adoption state once a position is genuinely closed."""
        self._adoptions.pop(symbol, None)

    async def adopt_orphan(self, broker_pos: dict):
        """
        Adopt an orphaned broker position (manual trade detection).

        Called when broker has a position not tracked internally.
        Fires within 6 seconds of your manual entry during market hours.

        Steps:
          1. Idempotency guard — skip if already adopted
          2. Compute tick-safe SL price
          3. Place emergency SL with tick rounding (same as _round_sl_to_tick)
          4. Register in order_manager.active_positions + hard_stops
          5. Log to DB via db.log_trade_entry() — CRITICAL: prevents infinite re-detection
          6. Set _db_dirty = True — forces fresh DB fetch next cycle
          7. Acquire capital slot (or emit CRITICAL alert if slot occupied)
          8. Send Telegram MANUAL ENTRY ADOPTED alert
        """
        symbol = broker_pos.get("symbol")
        qty = abs(broker_pos.get("qty", 0))
        net_qty = broker_pos.get("qty", 0)
        side = "SHORT" if net_qty < 0 else "LONG"
        avg_price = broker_pos.get("avg_price", 0.0)

        # The cost basis decides every P&L number this position will ever produce,
        # so exhaust the authoritative sources before estimating one. The WS cache
        # often has no avg_price yet; REST always does.
        basis_estimated = False
        if not avg_price:
            try:
                for bp in await self.broker.get_all_positions(force_rest=True):
                    if bp.get("symbol") == symbol and bp.get("qty", 0) != 0:
                        avg_price = bp.get("avgPrice", 0.0) or 0.0
                        if avg_price:
                            logger.info(
                                "[ADOPT] %s real avg price from REST: ₹%.2f", symbol, avg_price
                            )
                        break
            except Exception as e:
                logger.warning(f"[ADOPT] REST avg_price lookup failed for {symbol}: {e}")

        # Last resort only. LTP is the price NOW, not the price paid, so a P&L
        # computed against it is fiction — on 2026-09-09 it reported NSE:GRAPHITE-EQ
        # at -₹23.40 when the real figure on those shares was -₹3.70, and wrote
        # PNL=0.00% into the ML dataset. Flagged so nothing downstream trusts it.
        if not avg_price:
            try:
                avg_price = await self.broker.get_ltp(symbol) or 0.0
                basis_estimated = True
                logger.warning(
                    "[ADOPT] %s has no real avg price — falling back to LTP ₹%.2f. "
                    "P&L for this position is an ESTIMATE and is excluded from ML.",
                    symbol,
                    avg_price,
                )
            except Exception as e:
                logger.error(f"[ADOPT] LTP fallback failed for {symbol}: {e}")

        if not symbol or qty == 0:
            logger.error(f"[ADOPT] Cannot adopt — invalid broker_pos: {broker_pos}")
            return

        if avg_price <= 0:
            logger.critical(
                f"[ADOPT] ❌ Cannot adopt {symbol} — avg_price is 0 and LTP fallback failed. POSITION IS NAKED."
            )
            if self.telegram:
                await self.telegram.send_alert(
                    f"🚨 **ORPHAN ADOPTION FAILED**\n\n"
                    f"Symbol: `{symbol}`\n"
                    f"Reason: Cannot determine entry price (avg_price=0, LTP failed)\n"
                    f"⚠️ **Close this position manually NOW.**"
                )
            return

        # Idempotency guard
        # If symbol already registered, a prior adoption cycle completed successfully.
        # Do not place another SL or overwrite state.
        if self.order_manager and symbol in self.order_manager.active_positions:
            logger.debug(f"[ADOPT] {symbol} already in active_positions — no-op.")
            return

        logger.critical(
            f"[ADOPT] 🚨 MANUAL ENTRY DETECTED: {symbol} {side} ×{qty} "
            f"@ avg ₹{avg_price:.2f} — starting adoption."
        )

        # Tick size is NOT in the position payload, so defaulting to 0.05 left
        # NSE:TIINDIA-EQ (0.10 tick) naked after two rejected stops. Order of
        # authority: a tick learned from a past rejection, then the depth feed,
        # then the payload, then a default known to be wrong for 0.10 symbols.
        tick_size = _LEARNED_TICKS.get(symbol)
        if not tick_size:
            try:
                tick_size = await self.broker.get_tick_size(symbol)
            except Exception:
                tick_size = None
        if not tick_size:
            tick_size = broker_pos.get("tick_size") or 0.05
        sl_side = "BUY" if side == "SHORT" else "SELL"

        try:
            # Step 0: is this position already protected?
            # The operator may be running their own stop, or ours may still be
            # live from an earlier adoption. Either way, do not place a second.
            existing = await self._find_live_protective_order(symbol, sl_side)
            if existing:
                prior = self._adoptions.get(symbol, {})
                self._adoptions[symbol] = {
                    **prior,
                    "sl_id": existing,
                    "qty": qty,
                    "adopted_at": prior.get("adopted_at", time.time()),
                }
                logger.info(
                    "[ADOPT] %s already protected by live order %s — "
                    "adopting without placing another.",
                    symbol,
                    existing,
                )
                sl_id = existing
                sl_price = 0.0

            # Step 1: Compute tick-safe SL price
            sl_pct = 0.01  # emergency 1% SL for adopted orphan
            raw_sl = avg_price * (1 + sl_pct) if side == "SHORT" else avg_price * (1 - sl_pct)
            sl_id = existing
            last_err = None
            if not existing:
                sl_price = round_stop_away_from_entry(raw_sl, tick_size, side)
                logger.info(
                    f"[ADOPT] SL calc: raw=₹{raw_sl:.4f} → tick_rounded=₹{sl_price:.2f} "
                    f"(tick={tick_size})"
                )

            # Step 2: Place emergency SL, learning the tick if rejected
            for attempt in (1, 2) if not existing else ():
                try:
                    sl_id = await self.broker.place_order(
                        symbol=symbol,
                        side=sl_side,
                        qty=qty,
                        order_type="SL_MARKET",
                        trigger_price=sl_price,
                    )
                    if sl_id:
                        logger.critical(
                            f"[ADOPT] ✅ Emergency SL placed: {symbol} | "
                            f"sl_id={sl_id} | stop=₹{sl_price:.2f}"
                        )
                        break
                    last_err = "broker returned no order id"
                except Exception as e:
                    last_err = str(e)
                    sl_id = None

                # The rejection states the true tick. Re-round and try once more.
                learned = learn_tick_from_error(symbol, last_err) if attempt == 1 else None
                if learned:
                    tick_size = learned
                    sl_price = round_stop_away_from_entry(raw_sl, tick_size, side)
                    logger.warning(
                        "[ADOPT] retrying %s stop at ₹%.2f on learned tick %.4f",
                        symbol,
                        sl_price,
                        tick_size,
                    )
                    continue
                break

            if sl_id:
                prior = self._adoptions.get(symbol, {})
                self._adoptions[symbol] = {
                    **prior,
                    "sl_id": sl_id,
                    "qty": qty,
                    "adopted_at": prior.get("adopted_at", time.time()),
                    "naked_alerted_at": 0.0,
                }
            else:
                # Alert once per cooldown rather than on every 6s reconcile pass.
                prior = self._adoptions.get(symbol, {})
                last_alert = prior.get("naked_alerted_at", 0.0)
                _alert_before = last_alert
                self._adoptions[symbol] = {
                    **prior,
                    "sl_id": None,
                    "qty": qty,
                    "adopted_at": prior.get("adopted_at", time.time()),
                    "naked_alerted_at": (
                        time.time()
                        if time.time() - last_alert > self._naked_alert_cooldown
                        else last_alert
                    ),
                }
                logger.critical(
                    f"[ADOPT] ❌ Emergency SL FAILED for {symbol}: {last_err} | "
                    f"POSITION IS NAKED — manual close required immediately"
                )
                # Only alert when the cooldown allows it. Reconciliation runs
                # every 6s; on 18 Aug that would have meant hundreds of
                # identical "position is naked" messages.
                if self.telegram and self._adoptions[symbol]["naked_alerted_at"] >= _alert_before:
                    await self.telegram.send_alert(
                        f"🚨 *ORPHAN SL FAILED*\n\n"
                        f"Symbol: `{symbol}` {side} ×{qty}\n"
                        f"Avg: ₹{avg_price:.2f} | SL attempted: ₹{sl_price:.2f}\n"
                        f"Error: `{str(last_err)[:100]}`\n"
                        f"⚠️ **Position is NAKED. Close manually NOW.**"
                    )

            # Step 3: Register in order_manager internal state
            if self.order_manager:
                self.order_manager.active_positions[symbol] = {
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "entry_id": "MANUAL_ENTRY",
                    "sl_id": sl_id,
                    "status": "OPEN",
                    "entry_time": datetime.utcnow(),
                    "entry_price": avg_price,
                    "stop_loss": sl_price if sl_id else 0.0,
                    "source": "MANUAL_ENTRY_ADOPTED",
                    "cost_basis_estimated": basis_estimated,
                }
                if sl_id:
                    self.order_manager.hard_stops[symbol] = sl_id
                logger.info(f"[ADOPT] Position registered in active_positions: {symbol}")

            # Step 4: log to DB. Persisting the adoption is what stops infinite
            # re-detection — until the position is in the DB, every cycle sees a
            # fresh orphan. One ordered fallback: the old chain had a middle branch
            # keyed on a nonexistent attribute that aborted the whole adoption.
            entry_payload = {
                "symbol": symbol,
                "direction": side,
                "qty": qty,
                "entry_price": avg_price,
                "order_id": "MANUAL_ENTRY",
                "sl_id": sl_id,
                "source": "ORPHAN_RECOVERY",
                "session_date": date.today(),
            }

            db_handle = (
                self.order_manager.db
                if (self.order_manager and getattr(self.order_manager, "db", None))
                else self.db
            )

            persisted = False
            if db_handle is not None:
                try:
                    await db_handle.log_trade_entry(entry_payload)
                    logger.info(f"[ADOPT] DB entry logged for {symbol} (state=OPEN)")
                    persisted = True
                except Exception as e:
                    logger.error(f"[ADOPT-DB] log_trade_entry failed: {e} — trying raw insert")

                if not persisted:
                    try:
                        await db_handle.execute(
                            """INSERT INTO positions (symbol, direction, qty, entry_price, state, opened_at)
                               VALUES ($1, $2, $3, $4, 'OPEN', NOW())
                               ON CONFLICT (symbol) DO UPDATE SET state='OPEN'""",
                            symbol,
                            side,
                            qty,
                            avg_price,
                        )
                        logger.info(f"[ADOPT] DB entry inserted via raw fallback for {symbol}")
                        persisted = True
                    except Exception as e:
                        logger.error(f"[ADOPT] Raw insert fallback failed: {e}")

            if not persisted:
                logger.critical(
                    "[ADOPT] ⚠️ %s adopted in memory but NOT persisted — it will be "
                    "re-detected as an orphan next cycle. Investigate the DB.",
                    symbol,
                )

            # Step 5: Mark DB dirty
            # Forces fresh DB read next reconcile cycle.
            # After fresh read, symbol will appear in db_positions → no longer an orphan.
            self._db_dirty = True
            logger.info(f"[ADOPT] _db_dirty set True for {symbol}")

            # Step 6: Acquire capital slot
            if self.capital:
                if self.capital.is_slot_free:
                    try:
                        await self.capital.acquire_slot(symbol)
                        logger.info(f"[ADOPT] ✅ Capital slot acquired for {symbol}")
                    except Exception as e:
                        logger.error(f"[ADOPT] acquire_slot failed: {e}")
                else:
                    # TWO POSITIONS OPEN: bot trade + manual trade simultaneously.
                    # Capital slot is held by bot's trade. Manual trade is unprotected.
                    # This is a dangerous state — operator MUST know immediately.
                    existing = self.capital.active_symbol
                    logger.critical(
                        f"[ADOPT] ⚠️ TWO POSITIONS OPEN: capital slot held by {existing}, "
                        f"cannot acquire for manual entry {symbol}. "
                        f"Manual trade is running WITHOUT capital tracking."
                    )
                    if self.telegram:
                        await self.telegram.send_alert(
                            f"🚨 *TWO POSITIONS OPEN — CRITICAL*\n\n"
                            f"Bot trade:    `{existing}` (capital slot held)\n"
                            f"Manual trade: `{symbol}` {side} ×{qty}\n\n"
                            f"Capital slot CANNOT be acquired for manual trade.\n"
                            f"⚠️ Manual trade has an SL but NO capital tracking.\n"
                            f"When `{existing}` closes, bot may enter a 3rd trade.\n\n"
                            f"**Recommended:** Close one position manually."
                        )

            # Step 7: Final Telegram alert
            sl_status = f"₹{sl_price:.2f} (id: {sl_id})" if sl_id else "FAILED ⚠️ Close manually!"
            cap_status = (
                "✅ Acquired"
                if (
                    self.capital
                    and not self.capital.is_slot_free
                    and self.capital.active_symbol == symbol
                )
                else "⚠️ Slot occupied by other trade"
            )

            if self.telegram:
                await self.telegram.send_alert(
                    f"🤝 *MANUAL ENTRY ADOPTED*\n\n"
                    f"Symbol:    `{symbol}`\n"
                    f"Side:      {side}\n"
                    f"Qty:       {qty}\n"
                    f"AvgPrice:  ₹{avg_price:.2f}\n"
                    f"EmergSL:   {sl_status}\n"
                    f"Capital:   {cap_status}\n\n"
                    f"Bot is now tracking this position.\n"
                    f"SL will fire automatically. Exit via Fyers or let SL hit."
                )

            logger.critical(
                f"[ADOPT] ✅ ADOPTION COMPLETE: {symbol} {side} ×{qty} "
                f"@ ₹{avg_price:.2f} | sl={sl_id} sl_price=₹{sl_price:.2f}"
            )

        except Exception as e:
            logger.critical(f"[ADOPT] ADOPTION FAILED for {symbol}: {e}", exc_info=True)
            if self.telegram:
                await self.telegram.send_alert(
                    f"🔥 *ORPHAN ADOPTION FAILED*\n`{symbol}`\n`{str(e)[:150]}`\n"
                    f"Manual intervention required."
                )

    async def _handle_divergence(self, db_pos, broker_pos, orphans, phantoms, mismatched):
        """
        Detect + ACT on state divergence.
        Previous version: alert only.
        Now: adopts orphans, releases phantom capital slots.
        """
        if orphans:
            logger.critical(
                f"🚨 DISCREPANCY: Orphans={len(orphans)}, "
                f"Phantoms={len(phantoms)}, Mismatch={len(mismatched)}"
            )
        else:
            logger.warning(
                f"⚠️ DISCREPANCY (non-orphan): Orphans={len(orphans)}, "
                f"Phantoms={len(phantoms)}, Mismatch={len(mismatched)}"
            )

        # DB log (defensive — tries both column name conventions)
        async def _try_insert(int_col: str, brk_col: str) -> bool:
            try:
                await self.db.execute(
                    f"""
                    INSERT INTO reconciliation_log (
                        timestamp, {int_col}, {brk_col},
                        orphaned_positions, phantom_positions, quantity_mismatches,
                        status, session_date, check_duration_ms
                    ) VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7, 0)
                """,
                    len(db_pos),
                    len(broker_pos),
                    json.dumps(orphans),
                    json.dumps(phantoms),
                    json.dumps(mismatched),
                    "DIVERGENCE_DETECTED",
                    date.today(),
                )
                return True
            except Exception:
                return False

        inserted = False
        # Try long names first (new schema), then short names (old schema)
        for int_col, brk_col in [
            ("internal_position_count", "broker_position_count"),
            ("internal_pos_count", "broker_pos_count"),
        ]:
            inserted = await _try_insert(int_col, brk_col)
            if inserted:
                break

        if not inserted:
            # Auto-migrate: add missing JSON columns and retry
            try:
                for col in ["orphaned_positions", "phantom_positions", "quantity_mismatches"]:
                    await self.db.execute(f"""
                        ALTER TABLE reconciliation_log
                        ADD COLUMN IF NOT EXISTS {col} TEXT DEFAULT '[]'
                    """)
                logger.info(
                    "[RECONCILE] Auto-migrated reconciliation_log JSON columns. Retrying..."
                )
                for int_col, brk_col in [
                    ("internal_position_count", "broker_position_count"),
                    ("internal_pos_count", "broker_pos_count"),
                ]:
                    inserted = await _try_insert(int_col, brk_col)
                    if inserted:
                        break
                if not inserted:
                    logger.error(
                        "[RECONCILE] DB insert still failed after migration — discrepancy logged to file only"
                    )
            except Exception as migrate_err:
                logger.error(f"Reconciliation DB migration failed: {migrate_err}")

        # ORPHANS: broker has position, internal state doesn't
        for orphan in orphans:
            sym = orphan["symbol"]

            # Idempotency guard: if already in active_positions, do not re-adopt.
            # This prevents double-adoption when two reconcile cycles fire close together.
            if self.order_manager and sym in self.order_manager.active_positions:
                logger.debug(f"[ORPHAN] {sym} already in active_positions — skipping re-adoption.")
                continue

            logger.critical(
                f"🚨 ORPHAN DETECTED: {sym} qty={orphan['qty']} — adopting with emergency SL"
            )
            # adopt_orphan infers side from the SIGN of qty, so it must receive the
            # signed net quantity — passing the absolute value would label every
            # short as a LONG and place the emergency stop on the wrong side.
            src = broker_pos.get(sym, {})
            adopt_data = {
                "symbol": sym,
                "qty": src.get("net_qty", orphan.get("net_qty", orphan["qty"])),
                "avg_price": src.get("avg_price", 0.0),
            }
            await self.adopt_orphan(adopt_data)

        # PHANTOMS: internal state has position, broker doesn't
        # This fires when YOU manually close a position outside the bot.
        # We must: (1) run the full close path, (2) release capital, (3) reset DB cache.
        for phantom in phantoms:
            sym = phantom["symbol"]
            # Past the square-off deadline, flat-at-broker is the scheduler's own
            # doing. It fired as a CRITICAL on every EOD exit, and the DB recorded
            # the close as MANUAL_CLOSE_DETECTED — wrong on both counts.
            from shortcircuit.eod.eod_scheduler import EOD_TIME

            _eod_close = datetime.now(pytz.timezone("Asia/Kolkata")).time() >= EOD_TIME
            if _eod_close:
                logger.info(
                    f"🌆 [EOD] {sym} flat at broker after the square-off — running the close path."
                )
            else:
                logger.critical(
                    f"👻 POSITION VANISHED: {sym} — broker is flat but internal "
                    f"registry says open. Running full close path."
                )

            # Snapshot before the close path pops it from active_positions.
            # The exit classifier below needs entry price, qty and side, and by
            # Step 4 the registry entry is already gone.
            _closed_snapshot = dict(
                (self.order_manager.active_positions.get(sym) or {}) if self.order_manager else {}
            )

            # Step 1: Use _finalize_closed_position if order_manager has this symbol.
            # This handles: active_positions cleanup + hard_stops cleanup +
            #               capital.release_slot() + db.log_trade_exit() atomically.
            finalized = False
            if self.order_manager and sym in self.order_manager.active_positions:
                try:
                    # Fetch LTP for accurate PnL logging
                    pos = self.order_manager.active_positions[sym]
                    exit_price = 0.0
                    pnl = 0.0
                    try:
                        exit_price = await self.broker.get_ltp(sym) or 0.0
                        if exit_price > 0:
                            entry_price = pos.get("entry_price", 0.0)
                            qty = pos.get("qty", 0)
                            if entry_price > 0 and qty > 0:
                                # Direction-aware PnL
                                import shortcircuit.config as _cfg

                                _dir = pos.get("side", _cfg.TRADE_DIRECTION)
                                if _dir == "LONG":
                                    pnl = (exit_price - entry_price) * qty
                                else:
                                    pnl = (entry_price - exit_price) * qty
                    except Exception as e:
                        logger.warning(f"[GHOST] Could not fetch exit price for {sym}: {e}")

                    await self.order_manager._finalize_closed_position(
                        symbol=sym,
                        reason="EOD_SQUAREOFF" if _eod_close else "MANUAL_CLOSE_DETECTED",
                        exit_price=exit_price,
                        pnl=pnl,
                        send_alert=False,
                    )
                    finalized = True
                    logger.info(
                        f"[GHOST] _finalize_closed_position completed for {sym} — "
                        f"DB updated, capital released."
                    )
                except Exception as e:
                    logger.error(
                        f"[GHOST] _finalize_closed_position failed for {sym}: {e} — "
                        f"falling back to manual cleanup."
                    )

            if not finalized:
                # Fallback: manual cleanup if finalize failed or symbol wasn't in active_positions
                if self.order_manager:
                    self.order_manager.active_positions.pop(sym, None)
                    self.order_manager.hard_stops.pop(sym, None)
                    self.order_manager.exit_in_progress.pop(sym, None)

                # Hard-close the ghost position in the database to break the loop
                try:
                    await self.db.execute(
                        "UPDATE positions SET state = 'CLOSED', closed_at = NOW() WHERE symbol = $1 AND state = 'OPEN'",
                        sym,
                    )
                    logger.info(f"[GHOST] Hard-closed phantom position {sym} in database.")
                except Exception as e:
                    logger.error(f"[GHOST] Failed to hard-close phantom {sym} in DB: {e}")

            # Drop any orders left tracked for a symbol that is now flat.
            if hasattr(self.order_manager, "trade_manager"):
                self.order_manager.trade_manager.cleanup_active_orders(sym)
            elif hasattr(self, "trade_manager"):
                self.trade_manager.cleanup_active_orders(sym)

            # Step 2: release the capital slot if still occupied. Deliberately does
            # not check active_symbol == sym — this is a single-position bot, so any
            # phantom means the slot should be free, and leaving it held would block
            # every later trade.
            if self.capital and not self.capital.is_slot_free:
                try:
                    logger.critical(
                        f"🚨 [RECOVERY] Force-clearing slot for manually closed position: {sym}"
                    )
                    await self.capital.release_slot(broker=self.broker)
                    await self.capital.sync(self.broker)
                    logger.info("✅ [RECOVERY] Slot successfully released and capital synced.")
                except Exception as e:
                    logger.error(f"❌ [RECOVERY] Critical failure clearing slot for {sym}: {e}")
                    # Emergency direct reset. This previously assigned to
                    # `is_slot_free` / `active_symbol`, which are read-only
                    # properties — so the fallback itself raised AttributeError and
                    # the slot stayed locked for the rest of the session, blocking
                    # every subsequent entry.
                    try:
                        self.capital.force_reset_slot(reason=f"PHANTOM_{sym}")
                    except Exception as reset_err:
                        logger.critical(
                            "🚨 [RECOVERY] Force reset ALSO failed for %s: %s — "
                            "capital slot may be stuck. Restart required.",
                            sym,
                            reset_err,
                        )

            # Step 3: CRITICAL — mark DB dirty so next cycle re-fetches fresh positions.
            # Without this, _get_db_positions_cached() keeps returning stale cache
            # showing the position as OPEN → phantom detected every 6 seconds forever.
            self._db_dirty = True
            logger.info(f"[GHOST] _db_dirty set True for {sym} — DB will re-fetch next cycle.")

            # Step 4: Alert operator
            if self.telegram:
                _pos = (
                    (self.order_manager.active_positions.get(sym, {}) if self.order_manager else {})
                    or _closed_snapshot
                    or {}
                )
                try:
                    _reason, _exit_px, _pnl = await self._classify_exit(sym, _pos)
                except Exception as _cls_err:
                    logger.warning("[EXIT-CLASSIFY] %s failed: %s", sym, _cls_err)
                    _reason, _exit_px, _pnl = "MANUAL_EXIT", 0.0, 0.0

                _label = self.EXIT_LABELS.get(_reason, "👻 *POSITION CLOSED*")
                _entry = float(_pos.get("entry_price") or 0.0)
                _sign = "🟢" if _pnl >= 0 else "🔴"
                _detail = (
                    "Closed by the stop order the bot placed."
                    if _reason == "SL_HIT"
                    else "Closed by the 15:10 square-off."
                    if _reason == "EOD_SQUAREOFF"
                    else "You closed this position outside the bot."
                )
                await self.telegram.send_alert(
                    f"{_label}\n\n"
                    f"Symbol: `{sym}`\n"
                    + (f"Entry:  ₹{_entry:.2f}\n" if _entry > 0 else "")
                    + (f"Exit:   ₹{_exit_px:.2f}\n" if _exit_px > 0 else "")
                    + (
                        f"PnL:    {_sign} ₹{_pnl:.2f}\n"
                        if _exit_px > 0 and _entry > 0
                        else "PnL:    not computable (entry or exit price unknown)\n"
                    )
                    + f"Reason: `{_reason}`\n\n"
                    f"{_detail}\n"
                    f"✅ Bot state synced.\n"
                    f"✅ Capital slot released.\n"
                    f"✅ DB position marked CLOSED."
                )

        # MISMATCHED: qty differs
        for mm in mismatched:
            logger.critical(
                f"⚠️ QTY MISMATCH: {mm['symbol']} "
                f"db_qty={mm['db_qty']} broker_qty={mm['broker_qty']}"
            )
            if self.telegram:
                await self.telegram.send_alert(
                    f"⚠️ *QTY MISMATCH*\n\n"
                    f"Symbol: `{mm['symbol']}`\n"
                    f"Internal: {mm['db_qty']} | Broker: {mm['broker_qty']}\n"
                    f"Manual review required."
                )

    def _get_reconciliation_interval(self) -> int:
        if self._is_market_hours():
            return 6
        return 30 if self._has_open_positions else 300

    def _is_market_hours(self) -> bool:
        try:
            import pytz

            IST = pytz.timezone("Asia/Kolkata")
            now = datetime.now(IST)
        except Exception:
            now = datetime.now()
        if now.weekday() >= 5:
            return False
        return dtime(9, 15) <= now.time() <= dtime(15, 30)
