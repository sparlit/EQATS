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


"""Boot-time recovery of positions the bot did not open itself.

A restart mid-session can find live positions at the broker with no local
state — a crash, a redeploy, or a manual trade. This adopts them and places an
emergency stop rather than leaving them unmanaged.
"""
import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class StartupRecovery:
    def __init__(self, fyers_client, order_manager=None, capital_manager=None, telegram=None):
        self.fyers = fyers_client
        self.order_manager = order_manager
        self.capital = capital_manager
        self.telegram = telegram
        logger.info("[RECOVERY] StartupRecovery initialized (Phase 44.6 — adoption enabled).")

    async def scan_orphaned_trades(self):
        """
        Asynchronous startup scan with strict timeout.
        Adopts orphans and recovers state if any are found.
        """
        try:
            # Enforce strict timeout to prevent indefinite sync hangs
            positions = await asyncio.wait_for(
                asyncio.to_thread(self.fyers.positions), timeout=15.0
            )

            if positions.get("s") != "ok":
                logger.error(f"Recovery scan failed: {positions}")
                return

            net_positions = positions.get("netPositions", [])
            open_positions = [p for p in net_positions if p["netQty"] != 0]

            if not open_positions:
                logger.info("✅ [RECOVERY] No orphaned positions found (Broker is Flat).")
                return

            logger.critical(
                f"⚠️ [RECOVERY] Found {len(open_positions)} OPEN POSITION(S) at startup!"
            )
            for p in open_positions:
                sym = p["symbol"]
                qty = p["netQty"]
                side = "SHORT" if qty < 0 else "LONG"
                avg = p.get("avgPrice", 0.0)
                logger.critical(f"   - {sym}: qty={qty} ({side}) avgPrice=₹{avg:.2f}")

                # Attempt adoption instead of just logging
                if self.order_manager and self.capital:
                    try:
                        # Since we're now async, directly await the adoption
                        await self._adopt_orphan_async(sym, qty, side, avg)
                    except Exception as e:
                        logger.error(f"[RECOVERY] Failed to schedule adoption for {sym}: {e}")
                else:
                    # Fallback: alert only (old behaviour if managers not injected)
                    logger.critical(
                        f"[RECOVERY] order_manager/capital not injected — "
                        f"cannot adopt {sym}. Alert only."
                    )
                    if self.telegram:
                        asyncio.create_task(
                            self.telegram.send_alert(
                                f"⚠️ **ORPHAN AT STARTUP**: `{sym}` qty={qty}\n"
                                f"Cannot auto-adopt — managers not wired."
                            )
                        )

        except TimeoutError:
            logger.error(
                "❌ [RECOVERY] Fyers 'positions' API timed out after 15s. Skipping recovery."
            )
        except Exception as e:
            logger.error(f"Recovery scan failed: {e}")

    async def _adopt_orphan_async(self, symbol: str, net_qty: int, side: str, avg_price: float):
        """Async adoption logic — places emergency SL, registers position, locks capital."""
        qty = abs(net_qty)
        sl_pct = 0.01
        sl_price = (
            round(avg_price * (1 + sl_pct), 2)
            if side == "SHORT"
            else round(avg_price * (1 - sl_pct), 2)
        )
        sl_side = "BUY" if side == "SHORT" else "SELL"

        # Step 1: Place emergency SL
        sl_id = None
        try:
            sl_id = await self.order_manager.broker.place_order(
                symbol=symbol,
                side=sl_side,
                qty=qty,
                order_type="SL_MARKET",
                trigger_price=sl_price,
            )
            logger.critical(
                f"[RECOVERY] Emergency SL placed | {symbol} sl_id={sl_id} @ ₹{sl_price:.2f}"
            )
        except Exception as e:
            logger.critical(f"[RECOVERY] Emergency SL FAILED for {symbol}: {e} | NAKED POSITION")
            if self.telegram:
                await self.telegram.send_alert(
                    f"🚨 *STARTUP ORPHAN — SL FAILED*\n\n"
                    f"`{symbol}` qty={qty}\nSL error: `{e}`\n"
                    f"⚠️ Manual close required NOW"
                )

        # Step 2: Register in order_manager
        self.order_manager.active_positions[symbol] = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "entry_id": "STARTUP_ORPHAN",
            "sl_id": sl_id,
            "status": "OPEN",
            "entry_time": datetime.now(UTC),
            "entry_price": avg_price,
            "stop_loss": sl_price if sl_id else 0.0,
            "source": "STARTUP_ORPHAN_ADOPTED",
        }
        if sl_id:
            self.order_manager.hard_stops[symbol] = sl_id

        # Step 3: Lock capital slot
        try:
            if self.capital.is_slot_free:
                await self.capital.acquire_slot(symbol)
            else:
                logger.warning(
                    f"[RECOVERY] Capital slot occupied by {self.capital.active_symbol} "
                    f"— cannot lock for orphan {symbol}"
                )
        except Exception as e:
            logger.error(f"[RECOVERY] Capital acquire_slot failed: {e}")

        # Step 4: Alert
        if self.telegram:
            await self.telegram.send_alert(
                f"⚠️ *STARTUP ORPHAN ADOPTED*\n\n"
                f"Symbol:   `{symbol}`\n"
                f"Side:     {side}  Qty: {qty}\n"
                f"AvgPrice: ₹{avg_price:.2f}\n"
                f"EmergSL:  {'₹' + str(sl_price) if sl_id else '❌ FAILED'}\n\n"
                f"Bot is now managing this position."
            )
        logger.critical(
            f"[RECOVERY] ✅ Orphan adopted: {symbol} {side} ×{qty} sl_id={sl_id} sl=₹{sl_price:.2f}"
        )
