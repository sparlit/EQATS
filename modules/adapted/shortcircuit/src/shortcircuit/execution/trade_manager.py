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


import logging
from datetime import datetime

from shortcircuit.broker.rest_limiter import Priority, rest_limiter

logger = logging.getLogger(__name__)


class TradeManager:
    def __init__(self, fyers, capital_manager):
        self.fyers = fyers
        # Legacy Auto-Trade State (Now managed by TelegramBot)
        self.auto_trade_enabled = False  # Default to False always

        # Position Safety — Track active SL orders
        self.active_sl_orders = {}  # {symbol: order_id}

        # Capital Management (Injected)
        self.capital_manager = capital_manager

        # Reference to Telegram bot (set externally after init)
        self.bot = None

        # Reconciliation Engine (Injected)
        self.reconciliation_engine = None

        # Order Manager (Injected). The EOD square-off needs it to tell a position
        # the bot is tracking from one it is not — see close_all_positions.
        self.order_manager = None

        # Scalper Position Manager (Injected)
        self.scalper_manager = None

    # Position safety: critical guards

    def _get_broker_position(self, symbol: str) -> dict:
        """
        Query broker for ACTUAL current position.

        Returns:
            dict with 'net_qty', 'symbol', 'raw' or None on error
        """
        try:
            rest_limiter.acquire(priority=Priority.HIGH)
            positions = self.fyers.positions()

            if positions.get("s") != "ok" and "netPositions" not in positions:
                logger.error(f"[SAFETY] Could not fetch positions: {positions}")
                return None

            for pos in positions.get("netPositions", []):
                if pos["symbol"] == symbol:
                    return {"net_qty": pos["netQty"], "symbol": symbol, "raw": pos}

            # Symbol not in positions = FLAT
            return {"net_qty": 0, "symbol": symbol, "raw": None}

        except Exception as e:
            logger.error(f"[SAFETY] Broker position query failed: {e}")
            return None

    def cleanup_active_orders(self, symbol: str):
        """
        Cancels all pending orders for a symbol.
        Called after TP/SL hit or manual exit.
        """
        logger.info(f"🧹 [SAFETY] Cleaning up orphaned orders for {symbol}")
        try:
            rest_limiter.acquire(priority=Priority.HIGH)
            orders = self.fyers.orderbook()
            if "orderBook" not in orders:
                return

            for order in orders["orderBook"]:
                if order["symbol"] == symbol and order["status"] in [6]:  # 6=Pending
                    logger.warning(
                        f"❌ [SAFETY] Cancelling orphaned order: {order['id']} ({order['type']})"
                    )
                    self.fyers.cancel_order(data={"id": order["id"]})
        except Exception as e:
            logger.error(f"❌ [SAFETY] Order cleanup failed for {symbol}: {e}")

    def close_all_positions(self):
        """
        Closes all open intraday positions.
        Used for EOD Auto-Square Off.
        Releases capital for each closed position.
        """
        logger.warning("[ALERT] INITIATING AUTO-SQUARE OFF...")
        try:
            rest_limiter.acquire(priority=Priority.HIGH)
            positions_response = self.fyers.positions()
            if "netPositions" not in positions_response:
                logger.info("No positions to close.")

            # Cancel all pending orders first
            try:
                rest_limiter.acquire(priority=Priority.HIGH)
                orders = self.fyers.orderbook()
                if "orderBook" in orders:
                    cleaned = 0
                    for o in orders["orderBook"]:
                        if o["status"] in [6]:  # Pending
                            self.fyers.cancel_order(data={"id": o["id"]})
                            cleaned += 1
                    logger.info(f"EOD Cleanup: Cancelled {cleaned} pending orders.")
            except Exception as e:
                logger.error(f"EOD Order Cleanup Failed: {e}")

            if "netPositions" not in positions_response:
                return "Checked Orders. No open positions."

            closed_count = 0
            for pos in positions_response["netPositions"]:
                net_qty = pos["netQty"]
                symbol = pos["symbol"]

                if net_qty != 0:
                    exit_side = -1 if net_qty > 0 else 1
                    exit_qty = abs(net_qty)

                    data = {
                        "symbol": symbol,
                        "qty": exit_qty,
                        "type": 2,
                        "side": exit_side,
                        "productType": pos["productType"],
                        "limitPrice": 0,
                        "stopPrice": 0,
                        "validity": "DAY",
                        "disclosedQty": 0,
                        "offlineOrder": False,
                    }

                    logger.info(f"[EOD] Squaring off {symbol}: Qty {exit_qty} Side {exit_side}")
                    res = self.fyers.place_order(data=data)
                    logger.info(f"Square-off Response: {res}")

                    # PnL for the session risk tracker. Do not read pos['lp'] —
                    # Fyers netPositions carry no lp/ltp, so exit_price was always
                    # 0 and every EOD square-off logged ₹0 into MAX_SESSION_LOSS,
                    # making a day closed by square-off look risk-free.
                    pnl_estimate = self._estimate_exit_pnl(pos, symbol, net_qty)

                    logger.info(f"[EXIT] {symbol} reason=EOD_SQUAREOFF pnl=₹{pnl_estimate:.2f}")

                    # Book the outcome only for a position nobody else will book.
                    # A position the order manager is tracking gets exactly one
                    # outcome, from its close path (_finalize_closed_position), which
                    # also writes the ML label, the DB exit and the capital release.
                    # Booking it here as well counted every square-off twice: on
                    # 23 Sep NSE:JAYKAY-EQ made ₹35.50 and session PnL read ₹71.45.
                    # That was rare while trades seldom reached 15:10; EOD_HOLD sends
                    # every surviving trade there.
                    om = self.order_manager
                    tracked = om is not None and symbol in getattr(om, "active_positions", {})
                    if tracked:
                        logger.info("[EOD] %s is tracked — outcome left to its close path", symbol)
                    else:
                        try:
                            self.record_trade_outcome(symbol, pnl_estimate)
                        except Exception as e:
                            logger.error(f"G13 outcome recording failed in square-off: {e}")

                    closed_count += 1

                    # Clean up SL tracking
                    self._cleanup_sl_tracking(symbol)

                    # Capital is released by the main loop, not here.
                    pass

                    # Mark Dirty
                    if self.reconciliation_engine:
                        self.reconciliation_engine.mark_dirty()

            return f"Squaring Off Complete. Closed {closed_count} positions."

        except Exception as e:
            logger.error(f"Auto-Square Off Failed: {e}")
            return f"Square Off Error: {e}"

    def _estimate_exit_pnl(self, pos: dict, symbol: str, net_qty: int) -> float:
        """
        Best available PnL estimate for a position being squared off.

        Preference order:
          1. Broker-reported realised + unrealised P&L — exact, no extra call.
          2. Mark-to-market against a freshly fetched LTP.
          3. 0.0, logged loudly, so a missing number is never mistaken for a flat day.
        """
        # 1. Broker's own numbers.
        try:
            realised = float(pos.get("realized_profit", 0) or 0)
            unrealised = float(pos.get("unrealized_profit", 0) or 0)
            if realised or unrealised:
                return realised + unrealised
        except (TypeError, ValueError):
            pass

        # 2. Mark to market. netAvg is the true entry for both sides.
        try:
            entry = float(
                pos.get("netAvg")
                or pos.get("avgPrice")
                or (pos.get("sellAvg") if net_qty < 0 else pos.get("buyAvg"))
                or 0
            )
            if entry <= 0:
                raise ValueError("no usable entry price")

            quote = self.fyers.quotes(data={"symbols": symbol})
            ltp = 0.0
            if isinstance(quote, dict) and quote.get("d"):
                ltp = float(quote["d"][0].get("v", {}).get("lp", 0) or 0)

            if ltp > 0:
                qty = abs(net_qty)
                return (entry - ltp) * qty if net_qty < 0 else (ltp - entry) * qty
        except Exception as e:
            logger.warning(f"[EOD] Mark-to-market failed for {symbol}: {e}")

        logger.error(
            "[EOD] Could not determine PnL for %s — recording 0.0. "
            "Session loss tracking is understated for this trade.",
            symbol,
        )
        return 0.0

    def record_trade_outcome(self, symbol: str, pnl: float):
        """
        Phase 69 [G13]: Record trade outcome in SignalManager.
        Updates daily PnL tracking and global stats.
        """
        from shortcircuit.execution.signal_manager import get_signal_manager

        sm = get_signal_manager()
        sm.record_outcome(symbol, pnl)
        logger.info(f"Phase 69 Outcome recorded for {symbol}: ₹{pnl:.2f}")

    # Safety utilities

    def _cleanup_sl_tracking(self, symbol: str):
        """Remove SL tracking after position closed."""
        if symbol in self.active_sl_orders:
            del self.active_sl_orders[symbol]
            logger.info(f"[SAFETY] SL tracking cleaned up for {symbol}")
