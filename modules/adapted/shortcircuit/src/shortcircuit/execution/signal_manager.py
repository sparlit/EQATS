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
Signal Manager Module
Handles daily signal caps, per-symbol cooldowns, and consecutive loss tracking.
Based on Volman's principle: "Quality over quantity - 80% of profits from 20% of trades."
"""
import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta

from shortcircuit import config

logger = logging.getLogger(__name__)


class SignalManager:
    """
    Manages signal flow to prevent overtrading and enforce quality filters.
    """

    def __init__(self, cooldown_minutes=45):
        self.cooldown_minutes = cooldown_minutes

        # Daily tracking
        self.signals_today = []
        self.current_date = None

        # Per-symbol tracking
        self.last_signal_time = {}  # symbol -> datetime

        # PnL tracking for auto-pause
        self.daily_pnl = 0.0
        self.max_session_loss = getattr(config, "MAX_SESSION_LOSS_INR", 500.0)
        self.is_paused = False
        self.daily_target_inr: float = 0.0  # Dynamic target calculated at startup

        # Stats
        self.stats = defaultdict(int)
        self._lock = threading.Lock()  # protect list/dict from concurrent thread access
        self._exec_cooldowns: dict = {}  # symbol → datetime (unblock_at)

    def _reset_if_new_day(self):
        """Reset counters at the start of a new trading day."""
        today = datetime.now().date()

        if self.current_date != today:
            logger.info(f"New trading day: {today}. Resetting signal manager.")
            self.signals_today = []
            self.last_signal_time = {}
            self.daily_pnl = 0.0
            self.is_paused = False
            self.current_date = today
            self.stats = defaultdict(int)

    def can_signal(self, symbol, is_execution=False, confidence: str = ""):
        """
        Check if we can send a signal for this symbol.

        Args:
            symbol:       The stock symbol (e.g., "NSE:HINDCOPPER-EQ")
            is_execution: If True, skips discovery-level cooldown check
            confidence:   Signal confidence tier from G5 ('MEDIUM','HIGH','EXTREME','MAX_CONVICTION').
                          Used for the Daily Target gate — after 5% target is hit only
                          EXTREME or MAX_CONVICTION signals are allowed.

        Returns:
            tuple: (allowed, reason)
        """
        with self._lock:
            self._reset_if_new_day()
            now = datetime.now()

            # Check 0: Execution failure cooldown (Hard block on broker errors)
            cd = self._exec_cooldowns.get(symbol)
            if cd:
                now_ts = datetime.now()
                if now_ts < cd["blocked_until"]:
                    remaining = int((cd["blocked_until"] - now_ts).total_seconds())
                    self.stats["blocked_exec_cooldown"] = (
                        self.stats.get("blocked_exec_cooldown", 0) + 1
                    )
                    return False, f"Exec cooldown: {symbol} blocked {remaining}s ({cd['reason']})"
                else:
                    del self._exec_cooldowns[symbol]  # expired

            # Check 2: Paused due to max session loss
            if self.is_paused:
                self.stats["blocked_paused"] += 1
                return False, f"Trading paused: Max session loss reached (₹{self.daily_pnl:.2f})"

            # Check 3: Per-symbol cooldown (Discovery only)
            if not is_execution and symbol in self.last_signal_time:
                unlock_at = self.last_signal_time[symbol]
                if now < unlock_at:
                    remaining = (unlock_at - now).total_seconds() / 60
                    self.stats["blocked_cooldown"] += 1
                    return False, f"Cooldown: {symbol} blocked for {remaining:.1f}m"

            # Daily Target Gate
            # Once daily profit ≥ target, only EXTREME / MAX_CONVICTION allowed.
            # Favor dynamic_target_inr if config is set to -1.
            daily_target = getattr(config, "DAILY_TARGET_INR", 0)
            if daily_target == -1:
                daily_target = self.daily_target_inr

            if daily_target > 0 and self.daily_pnl >= daily_target:
                HIGH_CONVICTION = ("EXTREME", "MAX_CONVICTION")
                if confidence not in HIGH_CONVICTION:
                    self.stats["blocked_daily_target"] = (
                        self.stats.get("blocked_daily_target", 0) + 1
                    )
                    logger.info(
                        f"🎯 [DAILY TARGET] {symbol} skipped — target ₹{daily_target:.0f} hit "
                        f"(PnL=₹{self.daily_pnl:.2f}). Confidence '{confidence}' not EXTREME+."
                    )
                    return False, (
                        f"Daily target ₹{daily_target:.0f} hit — only EXTREME/MAX_CONVICTION allowed "
                        f"(got: {confidence or 'UNKNOWN'})"
                    )
                else:
                    logger.info(
                        f"⭐ [DAILY TARGET] {symbol} ALLOWED post-target "
                        f"— confidence={confidence} qualifies."
                    )

            return True, "OK"

    def record_signal(self, symbol, entry_price, stop_loss, pattern):
        """
        Record a new signal being sent.

        Args:
            symbol: Stock symbol
            entry_price: Entry price
            stop_loss: Stop loss price
            pattern: Pattern name
        """
        with self._lock:
            self._reset_if_new_day()
            now = datetime.now()

            signal_record = {
                "symbol": symbol,
                "time": now,
                "entry": entry_price,
                "stop": stop_loss,
                "pattern": pattern,
                "status": "OPEN",  # Will be updated when we track outcome
            }

            self.signals_today.append(signal_record)

            # G8.1: Per-symbol cooldown (Standard)
            cooldown = self.cooldown_minutes

            self.last_signal_time[symbol] = now + timedelta(minutes=cooldown)
            self.stats["signals_sent"] += 1

            logger.info(
                f"Signal recorded: {symbol} @ {entry_price} (#{len(self.signals_today)} today). Cooldown set: {cooldown}m"
            )

    def add_pending_signal(self, symbol: str):
        """
        Reduced cooldown for Pending signals.
        We no longer block the scanner if a signal is added but not yet executed.
        This allows 'Trailing' the signal until validation is passed.
        """
        with self._lock:
            # Deliberately does not set last_signal_time: the cooldown applies
            # only to successful executions, which record_signal handles.
            logger.info(f"G8.3 Pending Signal tracking: {symbol} (No cooldown set)")

    def record_outcome(self, symbol: str, pnl: float):
        """
        Record the outcome of a trade for daily PnL risk limits.

        Args:
            symbol: Stock symbol
            pnl: Realized PnL from the trade
        """
        self.daily_pnl += pnl
        is_win = pnl > 0

        if is_win:
            self.stats["wins"] += 1
            logger.info(
                f"WIN recorded for {symbol} (₹{pnl:.2f}). Session PnL: ₹{self.daily_pnl:.2f}"
            )
        else:
            self.stats["losses"] += 1
            logger.warning(
                f"LOSS recorded for {symbol} (₹{pnl:.2f}). Session PnL: ₹{self.daily_pnl:.2f}"
            )

            if self.daily_pnl <= -self.max_session_loss:
                self.is_paused = True
                logger.critical(
                    f"🚨 TRADING PAUSED: Max session loss limit breached. Session PnL: ₹{self.daily_pnl:.2f}"
                )

    def get_remaining_signals(self) -> int:
        """
        Signals still permitted today.

        focus_engine calls this after burning a slot; the method simply did not
        exist, so every successful entry logged
        "[SignalManager] record_signal failed (non-fatal): 'SignalManager' object
        has no attribute 'get_remaining_signals'" — harmless, but it made a normal
        entry look like a failure in the session log.

        There is no hard daily cap today (risk is bounded by MAX_SESSION_LOSS_INR
        and the single capital slot), so this reports headroom against the daily
        target gate rather than a fixed count.
        """
        with self._lock:
            self._reset_if_new_day()
            if self.is_paused:
                return 0
            daily_target = getattr(config, "DAILY_TARGET_INR", 0)
            if daily_target == -1:
                daily_target = self.daily_target_inr
            if daily_target > 0 and self.daily_pnl >= daily_target:
                return 0  # only EXTREME/MAX_CONVICTION pass the target gate
            return -1  # -1 == uncapped

    def get_status(self):
        """Get current status for operator commands and logging."""
        self._reset_if_new_day()
        return {
            "date": self.current_date,
            "signals_sent": len(self.signals_today),
            "signals_remaining": "Unlimited",
            "daily_pnl": self.daily_pnl,
            "is_paused": self.is_paused,
            "symbols_on_cooldown": list(self.last_signal_time.keys()),
            "stats": dict(self.stats),
        }


# Global singleton instance
_signal_manager = None


def get_signal_manager():
    """Get the global signal manager instance."""
    global _signal_manager
    if _signal_manager is None:
        _signal_manager = SignalManager(cooldown_minutes=45)
    return _signal_manager
