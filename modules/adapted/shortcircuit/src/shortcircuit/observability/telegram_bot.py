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
import contextlib
import logging
import random
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from shortcircuit import config
from telegram import (
    BotCommand,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)


def _he(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class SignalMsgState:
    created_at: float
    message_id: int | None = None


class ShortCircuitBot:
    """
    Telegram Bot — Command Interface.
    Responsibilities:
    - Auto-Trade Gate (single source of truth for auto_mode state)
    - Signal alerts (alert-only + interactive GO/SKIP buttons)
    - Live status, P&L, position, and broker-health commands
    - All user commands (/status, /why, /pnl, etc.)
    Auto Mode State:
    - Boots from config.AUTO_MODE, which is intentionally True. The bot is armed
      on startup by design; do NOT "restore" a False default here. Telegram was
      unreliable on this connection (ISP blocking), so requiring a manual /auto on
      each morning meant missed sessions.
    - Actual trading is still gated by config.TRADING_ENABLED, which MarketSession
      only sets True at 09:30 IST. Armed at boot != trading at boot.
    - The ONLY thing that disarms it is an explicit /auto off. Nothing turns it off
      automatically — a max-session-loss halt blocks signals via SignalManager
      without touching this flag.
    - Checked by trade_manager, focus_engine, order_manager via is_auto_mode().
    """

    def __init__(self, config_settings: dict, order_manager, capital_manager, focus_engine=None):
        self.config = config_settings
        self.order_manager = order_manager
        self.capital_manager = capital_manager
        self.focus_engine = focus_engine
        # Auto-Trade Gate
        self._auto_mode: bool = config_settings.get("AUTO_MODE", True)
        self._auto_on_queued: bool = False
        self._morning_brief_sent: bool = False
        # Telegram App
        self.bot_token = config_settings.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = str(config_settings.get("TELEGRAM_CHAT_ID"))
        self.app: Application | None = None
        self._ready_event = threading.Event()
        self._shutdown_event: asyncio.Event | None = None
        self._alert_queue = asyncio.Queue()
        self._throttler_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

        # State
        self._scanning_paused: bool = False
        self._editable_signal_flow_override: bool | None = None
        self._signal_msg_index: dict = {}
        # threading.Lock, not asyncio.Lock: this guards a plain dict touched from
        # both the event loop and synchronous done-callbacks, and is never held
        # across an await.
        self._signal_msg_index_lock = threading.Lock()
        self._scan_metadata: dict = {}

        # Injected by main.py after construction. Declared here so a command
        # arriving before wiring completes degrades gracefully instead of raising
        # AttributeError inside a handler.
        self.signal_manager = None
        self.market_session = None
        self._loop: asyncio.AbstractEventLoop | None = None

        logger.info(
            "🤖 Telegram Bot initialized | Auto Mode: %s",
            "ON" if self._auto_mode else "OFF",
        )

    # PUBLIC API — used by other modules
    def is_auto_mode(self) -> bool:
        """
        Single source of truth for the auto-trade gate.

        Also resolves a QUEUED activation. `/auto on` before 09:30 IST only sets
        `_auto_on_queued`, and the sole consumer of that flag was a one-shot check
        at the top of main._trading_loop. The loop starts at ~09:15, so any
        `/auto on` issued after that set a flag nobody ever read again: the user
        was told "activates at 09:30" and it silently never did.

        Resolving it here means it activates the moment any consumer asks —
        focus_engine, order_manager or /status — regardless of loop timing.
        """
        if self._auto_on_queued and not self._auto_mode:
            now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
            if (now_ist.hour, now_ist.minute) >= (9, 30):
                self._auto_mode = True
                self._auto_on_queued = False
                logger.critical(
                    "🟢 [AUTO] Queued Auto ON activated at %s IST",
                    now_ist.strftime("%H:%M:%S"),
                )
                self._notify_threadsafe("✅ *Auto Mode activated* — 09:30 reached, scanning live")
        return self._auto_mode

    def _notify_threadsafe(self, message: str) -> None:
        """
        Fire-and-forget alert callable from any thread.

        is_auto_mode() runs on the focus-engine thread as well as the event loop,
        so a bare create_task() here would raise "no running event loop".
        """
        loop = getattr(self, "_loop", None)
        try:
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(self.send_alert(message), loop)
                return
            asyncio.get_running_loop().create_task(self.send_alert(message))
        except RuntimeError:
            logger.info("[TELEGRAM] Alert skipped (no loop): %s", message[:60])
        except Exception as e:
            logger.warning(f"[TELEGRAM] threadsafe notify failed: {e}")

    def is_editable_signal_flow_enabled(self) -> bool:
        """Runtime override takes precedence over config default."""
        if self._editable_signal_flow_override is not None:
            return self._editable_signal_flow_override
        return bool(self.config.get("EDITABLE_SIGNAL_FLOW_ENABLED", False))

    async def send_message(self, text: str, parse_mode="HTML", reply_markup=None) -> Message | None:
        """
        Send a message to the authorized chat, degrading rather than dropping.

        Telegram rejects the ENTIRE message if the markup does not parse — an
        unescaped '<' in an error string, or a stray '*' in a broker message, is
        enough. For a trading bot that silently loses the alert saying a position
        is unprotected, which is exactly when you need it most.

        So: try the requested markup, and on a parse failure resend as plain text.
        A message with visible asterisks always beats no message.
        """
        if not self.app:
            return None

        try:
            return await self.app.bot.send_message(
                chat_id=self.chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup
            )
        except Exception as e:
            err = str(e).lower()
            parse_failure = (
                "can't parse" in err
                or "cant parse" in err
                or "entity" in err
                or "unsupported start tag" in err
            )
            if parse_mode is not None and parse_failure:
                logger.warning(
                    "Telegram %s parse failed (%s) — resending as plain text.",
                    parse_mode,
                    str(e)[:120],
                )
                try:
                    return await self.app.bot.send_message(
                        chat_id=self.chat_id, text=text, parse_mode=None, reply_markup=reply_markup
                    )
                except Exception as e2:
                    logger.error(f"Telegram plain-text fallback also failed: {e2}")
                    return None
            logger.error(f"Telegram send_message failed: {e}")
            return None

    async def edit_message(
        self, message_id: int, text: str, parse_mode="HTML", reply_markup=None
    ) -> bool:
        """Edit existing message."""
        if not self.app:
            return False
        try:
            await self.app.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return True
        except Exception as e:
            if "Message is not modified" in str(e):
                return True
            logger.error(f"Telegram edit_message failed: {e}")
            return False

    async def send_signal_discovery(self, signal: dict) -> int | None:
        """Async sender for non-blocking signal discovery messages."""
        msg = await self.send_message(self._build_signal_discovery_text(signal))
        return msg.message_id if msg else None

    async def queue_signal_discovery(self, signal: dict) -> str:
        """
        Non-blocking discovery queue.
        Returns correlation_id immediately without blocking scanner thread.
        """
        # threading.Lock, not asyncio.Lock: the index is a plain dict guarded for
        # short critical sections and touched from both the event loop and a
        # synchronous done-callback, where `async with` is impossible. Never held
        # across an await.
        correlation_id = str(uuid.uuid4())
        with self._signal_msg_index_lock:
            self._signal_msg_index[correlation_id] = SignalMsgState(created_at=time.time())

        if not self.app:
            logger.warning("[EDITABLE] Bot not ready for discovery queue")
            return correlation_id

        task = asyncio.create_task(self.send_signal_discovery(signal))

        def _on_discovery_done(done_task):
            try:
                message_id = done_task.result()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"[EDITABLE] Discovery send failed: {e}")
                return
            if message_id is None:
                return
            with self._signal_msg_index_lock:
                state = self._signal_msg_index.get(correlation_id)
                if state is not None:
                    state.message_id = message_id

        task.add_done_callback(_on_discovery_done)
        return correlation_id

    async def queue_signal_validation_update(
        self, correlation_id: str, signal: dict, outcome: str, details: dict | None = None
    ) -> None:
        """
        Queue validation update without blocking caller.
        """
        if not self.app:
            logger.warning(f"[EDITABLE] Bot not ready for validation update ({correlation_id})")
            return
        asyncio.create_task(
            self._handle_signal_validation_update(correlation_id, signal, outcome, details)
        )

    def _build_signal_discovery_text(self, signal: dict) -> str:
        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("side", "SHORT")
        ltp = signal.get("ltp", signal.get("entry_price", 0))
        trigger = signal.get("signal_low", signal.get("entry_price", 0))

        # Calculate pre-trade margin utilization
        margin_str = "N/A"
        if self.capital_manager and ltp > 0:
            qty, _, margin_req = self.capital_manager.compute_qty(symbol, ltp)
            margin_str = f"₹{margin_req:.0f} (Qty: {qty})"

        return (
            f"🔍 <b>SIGNAL DISCOVERED</b>\n\n"
            f"Symbol: <code>{_he(symbol)}</code>\n"
            f"Side: {side}\n"
            f"LTP: ₹{ltp:.2f}\n"
            f"Trigger: &lt; ₹{trigger:.2f}\n"
            f"Est. Margin: {margin_str}\n\n"
            f"<i>Waiting for Gate 12 validation...</i>"
        )

    def _build_signal_validation_text(
        self, signal: dict, outcome: str, details: dict | None = None
    ) -> str:
        details = details or {}
        symbol = signal.get("symbol", "UNKNOWN")
        ltp = details.get("ltp", signal.get("ltp", signal.get("entry_price", 0)))
        trigger = details.get(
            "trigger_price", signal.get("signal_low", signal.get("entry_price", 0))
        )
        reason = details.get("reason", "N/A")
        side = signal.get("side", "SHORT")
        entry = signal.get("entry_price", 0)
        stop = signal.get("stop_loss", 0)

        # Calculate pre-trade margin utilization
        margin_str = "N/A"
        qty = signal.get("quantity", 0)
        if qty > 0 and entry > 0:
            # Use the configured leverage, not a hardcoded 5. Entries fall back to
            # 4x on a margin rejection, which made this figure silently wrong.
            lev = getattr(self.capital_manager, "leverage", None) or getattr(
                config, "INTRADAY_LEVERAGE", 5.0
            )
            margin_str = f"₹{(qty * entry) / lev:.0f} (Qty: {qty})"
        elif self.capital_manager and ltp > 0:
            c_qty, _, margin_req = self.capital_manager.compute_qty(symbol, ltp)
            margin_str = f"₹{margin_req:.0f} (Qty: {c_qty})"

        if outcome == "VALIDATED":
            mode = "AUTO EXECUTION" if self.is_auto_mode() else "ALERT ONLY (AUTO OFF)"
            # No Target line: take-profit was removed. `signal['target']` was never
            # populated anyway, so this always rendered "Target: ₹0.00".
            return (
                f"✅ <b>GATE 12 VALIDATED</b>\n\n"
                f"Symbol: <code>{_he(symbol)}</code>\n"
                f"Side: {side}\n"
                f"LTP: ₹{ltp:.2f}\n"
                f"Trigger: &lt; ₹{trigger:.2f}\n"
                f"Est. Margin: {margin_str}\n"
                f"Entry: ₹{entry:.2f} | SL: ₹{stop:.2f}\n"
                f"Exit: SL or 15:10 square-off (no TP)\n"
                f"Action: {mode}\n"
                f"Reason: <code>{_he(reason)}</code>"
            )
        if outcome == "TIMEOUT":
            timeout_min = details.get("timeout_minutes", "N/A")
            return (
                f"⌛ <b>GATE 12 TIMEOUT</b>\n\n"
                f"Symbol: <code>{_he(symbol)}</code>\n"
                f"LTP: ₹{ltp:.2f}\n"
                f"Trigger: &lt; ₹{trigger:.2f}\n"
                f"Reason: <code>{_he(reason)}</code>\n"
                f"Timeout: {timeout_min} minute(s)"
            )
        return (
            f"⛔ <b>GATE 12 REJECTED</b>\n\n"
            f"Symbol: <code>{_he(symbol)}</code>\n"
            f"LTP: ₹{ltp:.2f}\n"
            f"Trigger: &lt; ₹{trigger:.2f}\n"
            f"Reason: <code>{_he(reason)}</code>"
        )

    async def _handle_signal_validation_update(
        self, correlation_id: str, signal: dict, outcome: str, details: dict | None = None
    ) -> None:
        message_id = None
        with self._signal_msg_index_lock:
            state = self._signal_msg_index.get(correlation_id)
            if state:
                message_id = state.message_id
        text = self._build_signal_validation_text(signal, outcome, details)
        try:
            edited = False
            if message_id:
                edited = await self.edit_message(
                    message_id=message_id, text=text, parse_mode="HTML"
                )
            if not edited:
                await self.send_message(text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"[EDITABLE] Validation update failed ({correlation_id}): {e}")
            with contextlib.suppress(Exception):
                await self.send_message(text, parse_mode="HTML")
        finally:
            with self._signal_msg_index_lock:
                self._signal_msg_index.pop(correlation_id, None)

    async def _cleanup_stale_signal_entries(self, now: float | None = None) -> int:
        """
        Single-pass stale entry cleanup. Returns number of entries removed.
        """
        now_ts = now if now is not None else time.time()
        removed = 0
        with self._signal_msg_index_lock:
            stale_keys = [
                key
                for key, state in self._signal_msg_index.items()
                if now_ts - state.created_at > 300
            ]
            for key in stale_keys:
                self._signal_msg_index.pop(key, None)
                removed += 1
        return removed

    async def _cleanup_stale_signal_entries_loop(self):
        while True:
            try:
                removed = await self._cleanup_stale_signal_entries()
                if removed:
                    logger.info(f"[EDITABLE] Cleaned {removed} stale signal message entries")
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EDITABLE] Stale cleanup loop failed: {e}")
                await asyncio.sleep(600)

    async def _start_cleanup_task(self):
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_signal_entries_loop())

    # SIGNAL ALERTS — called by trade_manager / focus_engine

    # Command handlers
    # HELPERS — build status snippets
    def _get_capital_block(self) -> str:
        """Build capital status block for command responses."""
        if not self.capital_manager:
            return "Capital: N/A\n"
        try:
            real_margin = self.capital_manager._real_margin
            bp = self.capital_manager.buying_power
            slot_status = self.capital_manager.get_slot_status()
            slot_str = (
                "🟢 FREE" if slot_status["slot_free"] else f"🔴 {slot_status['active_symbol']}"
            )

            margin_str = f"₹{real_margin:.0f}" if real_margin > 0 else "N/A"
            bp_str = f"₹{bp:.0f}" if bp > 0 else "N/A"

            return (
                f"Margin (Live): <b>{margin_str}</b>\n"
                f"Buying Power:  <b>{bp_str}</b>\n"
                f"Slot:          {slot_str}\n"
            )
        except Exception as e:
            logger.error(f"Failed to build capital block: {e}")
            return "Margin: Data Unavailable\n"

    def _get_signal_block(self) -> str:
        """Build signal manager status block."""
        if not self.signal_manager:
            return ""
        st = self.signal_manager.get_status()
        cb = "🔴 CIRCUIT BREAKER (MAX LOSS)" if st.get("is_paused") else "🟢 ACTIVE"
        return f"Signals:   {st.get('signals_sent', 0)} today | {cb}\n"

    def _get_session_block(self) -> str:
        """Build market session state block."""
        if not self.market_session:
            return ""
        try:
            state = self.market_session.get_current_state()
            state_map = {
                "PRE_MARKET": "🌅 PRE-MARKET",
                "EARLY_MARKET": "🌤️ EARLY (warmup)",
                "MID_MARKET": "☀️ PRIME",
                "EOD_WINDOW": "🌇 EOD WINDOW",
                "POST_MARKET": "🌙 CLOSED",
            }
            return f"Session:   {state_map.get(state, state)}\n"
        except Exception:
            return ""

    def _get_health_block(self) -> str:
        """Build infrastructure health block."""
        lines = []
        # Broker WebSocket
        if self.order_manager:
            broker = getattr(self.order_manager, "broker", None)
            if broker:
                data_ws = "✅" if getattr(broker, "data_ws_connected", False) else "❌"
                order_ws = "✅" if getattr(broker, "order_ws_connected", False) else "❌"
                lines.append(f"WS Data: {data_ws} | WS Order: {order_ws}")
        # Scan metadata
        scan_time = self._scan_metadata.get("last_scan_time")
        scan_count = self._scan_metadata.get("candidate_count", 0)
        scan_names = self._scan_metadata.get("candidate_names", [])
        if scan_time:
            if scan_count > 0 and scan_names:
                # Limit the display to max 10 symbols to prevent massive message spam
                display_names = scan_names[:10]
                names_str = ", ".join(display_names)
                if len(scan_names) > 10:
                    names_str += "..."
                lines.append(
                    f"Last Scan: {scan_time.strftime('%H:%M:%S')} ({scan_count} candidates: {names_str})"
                )
            else:
                lines.append(
                    f"Last Scan: {scan_time.strftime('%H:%M:%S')} ({scan_count} candidates)"
                )
        return "\n".join(lines) + "\n" if lines else ""

    # Command handlers
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/start — Welcome message."""
        if not self._is_authorized(update):
            return
        mode_str = "🟢 AUTO" if self.is_auto_mode() else "🔴 ALERT ONLY"
        # CapitalManager exposes `buying_power` (a property); there is no
        # `total_buying_power` attribute, so the old getattr always fell through
        # to its default and /start reported ₹0 no matter the real balance.
        bp = getattr(self.capital_manager, "buying_power", 0.0) if self.capital_manager else 0.0
        await update.message.reply_text(
            f"⚡ <b>ShortCircuit</b> is running.\n\n"
            f"Mode: <b>{_he(mode_str)}</b>\n"
            f"Buying Power: ₹{bp:.0f}\n\n"
            f"Send /help for all commands.\n"
            f"Send /auto on to enable trading.",
            parse_mode="HTML",
        )

    async def _cmd_auto_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/auto on — Enable auto trading. Returns preflight card."""
        # PREFLIGHT retained as marker for legacy UX coverage tests.
        if not self._is_authorized(update):
            await update.message.reply_text("⛔ Unauthorized.")
            return
        if self.is_auto_mode():
            await update.message.reply_text("ℹ️ Auto mode is already *ON*.", parse_mode="Markdown")
            return

        IST = ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(IST)
        earliest = now_ist.replace(hour=9, minute=30, second=0, microsecond=0)

        if now_ist < earliest:
            delta = earliest - now_ist
            mins_left = int(delta.total_seconds() // 60)
            self._auto_on_queued = True
            await update.message.reply_text(
                f"⏳ *Auto ON queued* — activates at 09:30 IST\n"
                f"_{mins_left} min remaining. No action needed._",
                parse_mode="Markdown",
            )
            return

        self._auto_mode = True
        self._auto_on_queued = False
        await update.message.reply_text(
            "✅ *Auto Mode ON* — scanning for live signals", parse_mode="Markdown"
        )

    async def _cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/mode buy|sell — Switch trade direction at runtime."""
        if not self._is_authorized(update):
            await update.message.reply_text("⛔ Unauthorized.")
            return
        args = context.args
        if not args:
            current = config.TRADE_DIRECTION
            emoji = "🟢 LONG (BUY)" if current == "LONG" else "🔴 SHORT (SELL)"
            await update.message.reply_text(
                f"Current mode: *{emoji}*\n\nUsage: `/mode buy` or `/mode sell`",
                parse_mode="Markdown",
            )
            return
        action = args[0].lower().strip()
        if action in ("buy", "long"):
            config.TRADE_DIRECTION = "LONG"
            logger.critical("🟢 [MODE] Trade direction switched to LONG (BUY) via Telegram")
            await update.message.reply_text(
                "🟢 *Mode: LONG (BUY)*\n\n"
                "Bot will now enter BUY positions.\n"
                "SL flips below entry.\n"
                "Exit remains SL or 15:10 square-off.\n\n"
                "_All other logic unchanged._",
                parse_mode="Markdown",
            )
        elif action in ("sell", "short"):
            config.TRADE_DIRECTION = "SHORT"
            logger.critical("🔴 [MODE] Trade direction switched to SHORT (SELL) via Telegram")
            await update.message.reply_text(
                "🔴 *Mode: SHORT (SELL)*\n\n"
                "Bot will now enter SELL positions (default).\n\n"
                "_All other logic unchanged._",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "Usage: `/mode buy` or `/mode sell`", parse_mode="Markdown"
            )

    async def _cmd_auto_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/auto off — Disable auto trading."""
        if not self._is_authorized(update):
            await update.message.reply_text("⛔ Unauthorized.")
            return
        if not self._auto_mode and not self._auto_on_queued:
            await update.message.reply_text("ℹ️ Auto mode is already *OFF*.", parse_mode="Markdown")
            return

        self._auto_mode = False
        self._auto_on_queued = False

        logger.critical("🛑 [AUTO] Auto-trading DISABLED via Telegram override (/auto off)")

        # Ensure immediate yield to event loop
        await asyncio.sleep(0)

        open_count = (
            len(self.order_manager.active_positions)
            if self.order_manager and hasattr(self.order_manager, "active_positions")
            else 0
        )
        text = (
            f"🛑 <b>AUTO TRADE OFF</b>\n"
            f"Mode: <b>ON</b> → OFF\n\n"
            f"{self._get_capital_block()}"
            f"Positions: {open_count} active (still managed)\n"
            f"{self._get_signal_block()}"
            f"\nSignals sent as alerts with GO/SKIP buttons.\n"
            f"Send /auto on to re-enable."
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/status — Full system health snapshot (Live Sync)."""
        if not self._is_authorized(update):
            return

        # Step 1: Force Live Sync from Fyers
        today_pnl = 0.0
        unrealised = 0.0
        open_positions = 0
        sync_success = True

        if self.order_manager and self.order_manager.broker:
            broker = self.order_manager.broker
            try:
                # Timeout Protection for Live Sync
                # Prevents /status from hanging when Fyers API is slow/down
                if self.capital_manager:
                    try:
                        await asyncio.wait_for(self.capital_manager.sync(broker), timeout=3.0)
                    except TimeoutError:
                        logger.warning("/status: Capital sync timed out. Using cached values.")

                # Sync Positions/PnL
                try:
                    trades = await asyncio.wait_for(
                        self.order_manager.get_today_trades(), timeout=3.0
                    )
                except TimeoutError:
                    logger.warning("/status: Trade sync timed out. Using cached values.")
                    # Fallback to local position cache if API hung
                    trades = []
                    for s, pos in getattr(self.order_manager, "active_positions", {}).items():
                        trades.append(
                            {
                                "symbol": s,
                                "realised_pnl": 0.0,  # Not in cache
                                "unrealised_pnl": pos.get("unrealised_pnl", 0.0),
                                "qty": pos.get("qty", 0),
                            }
                        )
                realised_pnl = sum(t.get("realised_pnl", 0.0) for t in trades)
                unrealised = sum(t.get("unrealised_pnl", 0.0) for t in trades)
                # Count only non-zero quantities as open
                open_positions = len([t for t in trades if t.get("qty", 0) != 0])
                today_pnl = realised_pnl

            except Exception as e:
                logger.error(f"Live sync failed in /status: {e}")
                sync_success = False
                # Fallback to local memory
                if self.signal_manager:
                    today_pnl = getattr(self.signal_manager, "daily_pnl", 0.0)
                if hasattr(self.order_manager, "active_positions"):
                    open_positions = len(self.order_manager.active_positions)
                    unrealised = sum(
                        p.get("unrealised_pnl", 0.0)
                        for p in self.order_manager.active_positions.values()
                    )

        mode_str = "🟢 AUTO" if self.is_auto_mode() else "🔴 ALERT ONLY"
        if self._scanning_paused:
            mode_str += " (⏸️ PAUSED)"
        dir_str = "🟢 LONG (BUY)" if config.TRADE_DIRECTION == "LONG" else "🔴 SHORT (SELL)"

        pnl_str = f"+₹{today_pnl:.2f}" if today_pnl >= 0 else f"-₹{abs(today_pnl):.2f}"
        unr_str = f"+₹{unrealised:.2f}" if unrealised >= 0 else f"-₹{abs(unrealised):.2f}"

        sync_indicator = "⚡ Live" if sync_success else "🕒 Cached"

        text = (
            f"📊 <b>ShortCircuit Status</b> ({sync_indicator})\n\n"
            f"Mode:      {mode_str}\n"
            f"Direction: {dir_str}\n"
            f"{self._get_session_block()}"
            f"\n━━━━━ CAPITAL ━━━━━\n"
            f"{self._get_capital_block()}"
            f"\n━━━━━ TRADING ━━━━━\n"
            f"Open:      {open_positions} position(s)\n"
            f"UnrlzdP&L: <b>{unr_str}</b>\n"
            f"DayP&L:    <b>{pnl_str}</b>\n"
            f"{self._get_signal_block()}"
            f"\n━━━━━ HEALTH ━━━━━\n"
            f"{self._get_health_block()}"
            f"\n<i>As of {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/help"""
        if not self._is_authorized(update):
            return
        await update.message.reply_text(
            "⚡ <b>ShortCircuit Commands</b>\n\n"
            "<b>/auto on|off</b>\n"
            "↳ Arm auto-trading or set to alert-only.\n\n"
            "<b>/mode buy|sell</b>\n"
            "↳ Switch between LONG (buy) and SHORT (sell) mode.\n\n"
            "<b>/status</b>\n"
            "↳ System health &amp; capital snapshot.\n\n"
            "<b>/health</b>\n"
            "↳ Broker WebSocket &amp; cache health dashboard.\n\n"
            "<b>/stop</b>\n"
            "↳ Emergency bot shutdown (requires confirmation).\n\n"
            "<i>Your bot is now in Minimalist Mode.</i>",
            parse_mode="HTML",
        )

    async def _cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/health — PRD-WS Phase 4: Full broker WebSocket health dashboard."""
        if not self._is_authorized(update):
            return

        broker = None
        if self.order_manager and hasattr(self.order_manager, "broker"):
            broker = self.order_manager.broker

        if not broker or not hasattr(broker, "get_health_report"):
            await update.message.reply_text("❓ Broker not available.")
            return

        try:
            r = broker.get_health_report()

            state = r.get("health_state", "UNKNOWN")
            state_icons = {
                "READY": "✅",
                "RECOVERED": "✅",
                "DEGRADED": "⚠️",
                "CRITICAL": "🟠",
                "SEVERE_DEGRADED": "🔴",
                "REPRIME_PENDING": "🔄",
                "FULL_RECONNECT_PENDING": "⚡",
                "HYBRID_REST_MODE": "🛑",
                "UNRECOVERABLE": "⛔",
                "PRIMING": "⏳",
                "CONNECTING": "🔌",
                "UNINITIALIZED": "❓",
            }
            icon = state_icons.get(state, "❓")

            dws = "✅ Connected" if r.get("data_ws_connected") else "❌ Disconnected"
            ows = "✅ Connected" if r.get("order_ws_connected") else "❌ Disconnected"
            dws_age = r.get("data_ws_last_event_age")
            dws_age_str = f" (last {dws_age:.0f}s ago)" if dws_age is not None else ""

            fresh_pct = r.get("fresh_pct", 0)
            fresh_icon = "✅" if fresh_pct >= 85 else ("⚠️" if fresh_pct >= 50 else "🔴")

            text = (
                f"🩺 <b>Broker Health Report</b>\n\n"
                f"State:         {icon} <b>{_he(state)}</b> ({r.get('time_in_state_secs', 0):.0f}s)\n\n"
                f"━━━━━ WEBSOCKETS ━━━━━\n"
                f"Data WS:       {_he(dws)}{_he(dws_age_str)}\n"
                f"  Reconnects:  {r.get('data_ws_reconnects', 0)}\n"
                f"Order WS:      {_he(ows)}\n"
                f"  Reconnects:  {r.get('order_ws_reconnects', 0)}\n\n"
                f"━━━━━ CACHE ━━━━━\n"
                f"Fresh:  {fresh_icon} {r.get('fresh_count', 0)}/{r.get('total_subscribed', 0)} ({fresh_pct:.1f}%)\n"
                f"Stale:         {r.get('stale_count', 0)}\n"
                f"Seeded (REST): {r.get('seeded_count', 0)}\n"
                f"Missing:       {r.get('missing_count', 0)}\n"
                f"Age P50/P95:   {r.get('age_p50', 0):.1f}s / {r.get('age_p95', 0):.1f}s\n\n"
                f"━━━━━ RECOVERY ━━━━━\n"
                f"Reprime attempts:  {r.get('total_reprime_attempts', 0)}\n"
                f"Reconnects:        {r.get('total_reconnect_attempts', 0)}\n"
                f"Consec. failures:  {r.get('consecutive_reprime_fails', 0)}\n\n"
                f"━━━━━ SESSION ━━━━━\n"
                f"Time degraded:     {r.get('session_degraded_secs', 0):.0f}s\n"
                f"Capital timeouts:  {r.get('capital_sync_timeouts', 0)}\n"
                f"Reconcile t/outs:  {r.get('reconcile_timeouts', 0)}\n"
                f"\n<i>As of {datetime.now().strftime('%H:%M:%S')}</i>"
            )
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"/health command error: {e}")
            await update.message.reply_text(f"❌ Health report error: {_he(str(e))}")

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/stop — Request bot termination with confirmation."""
        if not self._is_authorized(update):
            return

        keyboard = [
            [
                InlineKeyboardButton("🛑 YES, STOP BOT", callback_data="system_stop:confirm"),
                InlineKeyboardButton("❌ CANCEL", callback_data="system_stop:cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "⚠️ <b>CRITICAL: BOT TERMINATION REQUESTED</b>\n\n"
            "This will shut down ShortCircuit immediately. "
            "Pending orders will be cancelled and active positions will be closed if a supervisor cleanup is configured.\n\n"
            "<b>Are you absolutely sure?</b>",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    # HANDLERS
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not self._is_authorized_query(query):
            return
        data = query.data
        parts = data.split(":")
        action = parts[0]
        if action == "system_stop":
            sub_action = parts[1]
            if sub_action == "confirm":
                await self._handle_stop_confirm(query)
            else:
                await query.edit_message_text(
                    "✅ *Shutdown cancelled.* Bot continues monitoring.", parse_mode="Markdown"
                )

    async def _handle_stop_confirm(self, query):
        """Handle confirmed bot shutdown from /stop button."""
        logger.critical("🛑 [SHUTDOWN] Bot termination CONFIRMED via Telegram /stop")
        await query.edit_message_text(
            "🛑 **Shutting down ShortCircuit...**\n\n"
            "Cancelling pending orders and releasing resources.\n"
            "_This may take a few seconds._",
            parse_mode="Markdown",
        )
        # Fire the shutdown event if available
        if self._shutdown_event:
            self._shutdown_event.set()
        else:
            logger.error("[SHUTDOWN] No shutdown_event available — manual restart required")

    # EOD summary
    # Emergency alerts

    async def _send_morning_briefing(self, ws_cache, market_ctx, startup_validation_passed: bool):
        """Fires once at trading loop start. Never fires more than once per session."""
        if self._morning_brief_sent:
            return
        self._morning_brief_sent = True

        IST = ZoneInfo("Asia/Kolkata")
        now_dt = datetime.now(IST)
        now_str = now_dt.strftime("%H:%M IST")
        date_str = now_dt.strftime("%A, %d %b %Y")

        if market_ctx and getattr(market_ctx, "morning_range_valid", False):
            m_high = getattr(market_ctx, "morning_high", 0.0)
            m_low = getattr(market_ctx, "morning_low", 0.0)
            span = round(m_high - m_low, 2)
            range_line = (
                f"   High : {m_high:,.2f}\n   Low  : {m_low:,.2f}\n   Span : {span:,.2f} pts"
            )
        else:
            range_line = "   ⚠️ Unavailable (fetched after open)"

        snap = {}
        if ws_cache and hasattr(ws_cache, "cache_health_snapshot"):
            snap = ws_cache.cache_health_snapshot()

        fresh = snap.get("fresh", 0)
        total = snap.get("total", 0)
        fresh_pct = round(fresh / total * 100, 1) if total else 0.0

        # Read the ACTUAL socket state. This block used to print
        # "WS Data:  | WS Order: " unconditionally, so the first message of
        # every session claimed both sockets were healthy even when they were
        # down — precisely the morning you would want to know otherwise.
        data_ok = bool(getattr(ws_cache, "data_ws_connected", False))
        order_ok = bool(getattr(ws_cache, "order_ws_connected", False))
        ws_line = (
            f"   WS Data   : {'✅' if data_ok else '❌'} | WS Order: {'✅' if order_ok else '❌'}"
        )
        cache_line = (
            f"   WS Cache  : {fresh}/{total} live ({fresh_pct}%)"
            if total
            else "   WS Cache  : ⚠️ not primed"
        )

        if self.is_auto_mode():
            auto_str = "ON ✅"
        elif self._auto_on_queued:
            auto_str = "OFF (queued) ⏳"
        else:
            auto_str = "OFF ❌"

        dir_str = "🟢 LONG" if config.TRADE_DIRECTION == "LONG" else "🔴 SHORT"

        # Daily quote
        quote_text = self._get_daily_quote()

        message = (
            f"🌅 *ShortCircuit — Market Open*\n"
            f"📅 {date_str}\n\n"
            f"📚 *Trading Wisdom*\n"
            f"_{quote_text}_\n\n"
            f"📊 *NIFTY50 Morning Range*\n"
            f"{range_line}\n\n"
            f"🔌 *System Status*\n"
            f"{ws_line}\n"
            f"{cache_line}\n"
            f"   Candle API: {'✅ Verified' if startup_validation_passed else '❌ Failed'}\n"
            f"   DB Pool   : ✅ Connected\n"
            f"   Auto Mode : {auto_str}\n"
            f"   Direction : {dir_str}\n\n"
            f"⏱ Ready at {now_str} — scanning for setups"
        )

        await self.send_message(message, parse_mode="Markdown")
        logger.info("[TELEGRAM] Morning briefing sent")

    def _get_daily_quote(self) -> str:
        """Returns a random trading or motivational quote."""
        quotes = [
            "The goal of a successful trader is to make the best trades. Money is secondary. — Alexander Elder",
            "In trading, you have to be defensive and aggressive at the same time. — Paul Tudor Jones",
            "The trend is your friend until the end when it bends. — Ed Seykota",
            "Trading doesn't just reveal your character, it also builds it if you stay in the game. — Yvan Byeajee",
            "The market is a device for transferring money from the impatient to the patient. — Warren Buffett",
            "Cut your losses. Let your profits run. — Jesse Livermore",
            "Focus on the process, not the outcome. — Mark Douglas",
            "Amateurs hope. Professionals have a plan. — Traditional",
            "Volatility is the price you pay for performance. — Bill Miller",
            "Success in trading comes from the discipline of sticking to your system. — Jack Schwager",
            "Risk comes from not knowing what you're doing. — Warren Buffett",
            "You don't need to know what's going to happen next to make money. — Mark Douglas",
            "The best trades are the ones that are hard to take. — Traditional",
            "Edge is nothing more than an indication of a higher probability of one thing happening over another. — Mark Douglas",
            "Trading is about odds, not certainties. — Traditional",
            "A loss is a tuition fee for your trading education. — Traditional",
            "Patience is a weapon in the market. — Traditional",
            "Don't trade the P&L, trade the chart. — Traditional",
            "The stock market is never obvious. It is designed to fool most of the people, most of the time. — Jesse Livermore",
            "It's not whether you're right or wrong that's important, but how much money you make when you're right and how much you lose when you're wrong. — George Soros",
        ]
        return random.choice(quotes)

    # SETUP
    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("auto", self._cmd_auto))
        self.app.add_handler(CommandHandler("mode", self._cmd_mode))  # Phase 94
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("stop", self._cmd_stop))
        self.app.add_handler(CommandHandler("health", self._cmd_health))  # PRD-WS Phase 4
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def _cmd_auto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /auto on | /auto off")
            return
        if args[0] == "on":
            await self._cmd_auto_on(update, context)
        elif args[0] == "off":
            await self._cmd_auto_off(update, context)

    # COMPATIBILITY & UTILS
    async def send_alert(self, message: str):
        """
        Async alert sender. Callers must await this method.
        Used by TradeManager, FocusEngine (post Phase 44.5 � direct await).
        """
        if not self.app:
            return
        try:
            # Add to throttler queue
            await self._alert_queue.put(message)
        except Exception as e:
            logger.error(f"send_alert (queued) failed: {e}")

    async def _alert_throttler_loop(self):
        """
        Background task to process the alert queue with rate limiting.
        Bundles multiple fast alerts into a single message to avoid Telegram API lag.
        """
        logger.info("Telegram Alert Throttler started")
        last_send_time = 0.0

        while not self._shutdown_event or not self._shutdown_event.is_set():
            buffer = []
            try:
                # Wait for first message
                buffer.append(await self._alert_queue.get())

                # Check for burst (up to 0.5s wait for next if we have space)
                try:
                    while len(buffer) < 5:
                        buffer.append(await asyncio.wait_for(self._alert_queue.get(), timeout=0.5))
                except TimeoutError:
                    pass

                # Rate limiting (HZ)
                hz = getattr(config, "P81_TELEGRAM_RATE_LIMIT_HZ", 2) or 2
                interval = 1.0 / hz
                elapsed = time.time() - last_send_time
                if elapsed < interval:
                    await asyncio.sleep(interval - elapsed)

                # Alerts across the codebase are composed in Markdown
                # (*BOLD*, `code`). This previously sent them with send_message's
                # HTML default, so asterisks and backticks rendered literally and
                # any '<' or '&' in a broker error made Telegram reject the whole
                # bundle — losing up to 5 alerts at once.
                final_text = "\n\n".join(buffer)
                if len(final_text) > 4000:
                    final_text = final_text[:3900] + "\n\n...(truncated)..."

                sent = await self.send_message(final_text, parse_mode="Markdown")

                if sent is None and len(buffer) > 1:
                    # Bundling makes one bad message poison the batch. Retry the
                    # pieces individually so the good ones still arrive.
                    logger.warning(
                        "[TELEGRAM] Bundle of %d failed — resending individually.",
                        len(buffer),
                    )
                    for item in buffer:
                        await self.send_message(item, parse_mode="Markdown")

                last_send_time = time.time()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Throttler loop error: {e}")
                await asyncio.sleep(1)
            finally:
                # ALWAYS drain, even if the send raised. The previous version
                # cleared `buffer` only on the success path, so a failed send left
                # the messages in place and every later iteration re-sent them.
                for _ in range(len(buffer)):
                    try:
                        self._alert_queue.task_done()
                    except ValueError:
                        break

    # AUTHORIZATION — Security Gate
    def _is_authorized(self, update: Update) -> bool:
        """
        Verify command sender is authorized.
        Only the configured TELEGRAM_CHAT_ID can issue commands.
        Prevents random users from controlling your bot if token leaks.
        Args:
            update: Telegram Update object from command handler
        Returns:
            True if sender's chat ID matches config, False otherwise
        """
        if not update.effective_chat:
            return False
        incoming_chat_id = str(update.effective_chat.id)
        authorized_chat_id = self.chat_id
        if incoming_chat_id != authorized_chat_id:
            logger.warning(f"⚠️ Unauthorized command attempt from chat_id: {incoming_chat_id}")
            return False
        return True

    def _is_authorized_query(self, query) -> bool:
        """
        Verify inline button press is authorized.
        Used for [GO], [SKIP], [Refresh], [Close Now] button presses.
        Separate from _is_authorized because CallbackQuery has different
        attribute structure than Update.
        Args:
            query: CallbackQuery object from button handler
        Returns:
            True if button presser matches config, False otherwise
        """
        incoming_user_id = str(query.from_user.id)
        authorized_chat_id = self.chat_id
        # Note: For private chats, user.id == chat.id
        # For group chats, they differ (check both)
        if incoming_user_id != authorized_chat_id:
            # Try checking the chat ID as fallback
            incoming_chat_id = str(query.message.chat.id) if query.message else None
            if incoming_chat_id != authorized_chat_id:
                logger.warning(f"⚠️ Unauthorized button press from user_id: {incoming_user_id}")
                return False
        return True

    # Bot lifecycle
    async def start(self):
        self.app = Application.builder().token(self.bot_token).build()
        self._register_handlers()
        # Register global error handler (fixes PTB 'No error handlers' warning)
        self.app.add_error_handler(self._error_handler)
        await self.app.initialize()
        await self.app.start()
        # Capture the running loop for thread-safe calls
        self._loop = asyncio.get_running_loop()
        self._ready_event.set()
        await self._start_cleanup_task()
        await self.app.updater.start_polling(drop_pending_updates=True)

        # Telegram Command Menu
        if getattr(config, "P81_TELEGRAM_MENU_ENABLED", True):
            commands = [
                BotCommand("help", "Show all commands"),
                BotCommand("auto", "Toggle Trading (on/off)"),
                BotCommand("mode", "Switch BUY/SELL direction"),  # Phase 94
                BotCommand("status", "System Health Check"),
                BotCommand("stop", "🛑 TERMINATE BOT"),
            ]
            try:
                await self.app.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
                logger.info("Telegram Command Menu registered")
            except Exception as e:
                logger.error(f"Failed to register Telegram Menu: {e}")

        # Alert Throttler
        self._throttler_task = asyncio.create_task(self._alert_throttler_loop())
        logger.info("Telegram Bot started & Throttler active")

    async def run(self, shutdown_event: asyncio.Event):
        """
        Structured runtime entrypoint.
        Starts polling, waits for shutdown_event, then guarantees PTB teardown.
        """
        await self.start()
        self._shutdown_event = shutdown_event  # Store for /stop command
        try:
            await shutdown_event.wait()
        finally:
            logger.info("[TELEGRAM] Shutdown event received, stopping PTB.")
            await self.stop()

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """
        Global PTB error handler. Logs traceback + sends Telegram alert.
        Never crashes the bot.
        IMPORTANT: `update` is None when the error originates from network
        events, polling failures, or schedulers — not from a user message.
        Every `update.*` access MUST be guarded.
        """
        # Suppress transient DNS/network errors.
        error_str = str(context.error)
        transient_keywords = ("getaddrinfo", "NetworkError", "TimedOut", "ConnectionError")
        if any(kw in error_str or kw in type(context.error).__name__ for kw in transient_keywords):
            logger.warning(
                "[TELEGRAM] Transient network error: %s. PTB will auto-retry.", error_str[:200]
            )
            return  # Don't flood log with full traceback for DNS blips
        tb_string = traceback.format_exception(
            type(context.error), context.error, context.error.__traceback__
        )
        tb_text = "".join(tb_string)
        # Log full traceback
        logger.error(f"PTB Exception:\n{tb_text}")
        # Determine which handler caused it — update CAN be None
        handler_name = "Unknown (no update context)"
        if update is not None:
            try:
                eff_msg = getattr(update, "effective_message", None)
                cb_query = getattr(update, "callback_query", None)
                if eff_msg is not None:
                    msg_text = getattr(eff_msg, "text", None) or "N/A"
                    handler_name = f"Message: {msg_text[:50]}"
                elif cb_query is not None:
                    cb_data = getattr(cb_query, "data", None) or "N/A"
                    handler_name = f"Callback: {cb_data[:50]}"
                else:
                    handler_name = f"Update type: {type(update).__name__}"
            except Exception:
                handler_name = "Unknown (introspection failed)"
        # Send condensed alert to Telegram
        try:
            error_type = type(context.error).__name__
            short_tb = tb_text[-500:] if len(tb_text) > 500 else tb_text
            await self.send_message(
                f"⚠️ *BOT ERROR*\n\n"
                f"Type: `{error_type}`\n"
                f"Handler: {handler_name}\n\n"
                f"```\n{short_tb}\n```",
                parse_mode=None,
            )
        except Exception as e:
            logger.error(f"Failed to send error alert: {e}")

    def start_polling(self):
        """Compatibility wrapper for running in a thread from the supervisor."""
        raise RuntimeError("BRIDGE REMOVED in Phase 44.5. Use ShortCircuitBot.run(shutdown_event).")

    def send_validation_alert(self, signal):
        """Compat wrapper."""
        asyncio.create_task(
            self.send_alert(f"VALIDATION ALERT: {signal.get('symbol')} {signal.get('ltp')}")
        )

    async def stop(self):
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        if self.app is None:
            return
        updater = getattr(self.app, "updater", None)
        if updater is not None and getattr(updater, "running", False):
            await updater.stop()
        if getattr(self.app, "running", False):
            await self.app.stop()
        await self.app.shutdown()
