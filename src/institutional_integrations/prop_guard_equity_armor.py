"""
PropGuard Trailing Equity Armor Engine.
Implements TradeShield Protocol 4-Zone Equity Risk State Machine (Green, Yellow, Orange, Red),
Ratchet Peak Equity Tracking, Soft Warning Alert Thresholds (70%, 85%, 95%), and Hard
Kill-Switch Lockdown Execution with Cooldown Timers.
"""

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("PropGuardEquityArmor")


class PropGuardEquityArmorEngine:
    """
    TradeShield Protocol Trailing Equity Armor.
    """

    def __init__(
        self,
        daily_loss_limit_pct: float = 5.0,
        max_drawdown_pct: float = 10.0,
        kill_switch_cooldown_min: int = 30,
        soft_warning_1_pct: float = 70.0,
        soft_warning_2_pct: float = 85.0,
        soft_warning_3_pct: float = 95.0,
    ) -> None:
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.kill_switch_cooldown_s = kill_switch_cooldown_min * 60
        self.soft_warning_1_pct = soft_warning_1_pct
        self.soft_warning_2_pct = soft_warning_2_pct
        self.soft_warning_3_pct = soft_warning_3_pct
        self._lock = threading.Lock()
        self.peak_equity = 0.0
        self.lockdown_until = 0.0

    def update_equity_sample(
        self, current_equity: float, day_start_equity: float, initial_balance: float = 100000.0,
    ) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            self.peak_equity = max(self.peak_equity, current_equity)
            if now < self.lockdown_until:
                rem_sec = int(self.lockdown_until - now)
                return {
                    "zone": "RED",
                    "status": "HARD_LOCKDOWN",
                    "reason": f"Kill-Switch Lockdown Active ({rem_sec}s remaining)",
                    "action": "FLATTEN_AND_REJECT",
                    "current_equity": current_equity,
                    "peak_equity": self.peak_equity,
                    "drawdown_pct": 100.0,
                }
            daily_loss = day_start_equity - current_equity
            daily_loss_pct = daily_loss / day_start_equity * 100.0 if day_start_equity > 0 else 0.0
            trailing_dd = self.peak_equity - current_equity
            trailing_dd_pct = trailing_dd / self.peak_equity * 100.0 if self.peak_equity > 0 else 0.0
            daily_util_pct = daily_loss_pct / self.daily_loss_limit_pct * 100.0
            trailing_util_pct = trailing_dd_pct / self.max_drawdown_pct * 100.0
            max_util_pct = max(daily_util_pct, trailing_util_pct)
            zone = "GREEN"
            warning_level = 0
            action = "NONE"
            if max_util_pct >= 100.0:
                zone = "RED"
                action = "TRIGGER_KILL_SWITCH"
                self.lockdown_until = now + self.kill_switch_cooldown_s
            elif max_util_pct >= self.soft_warning_3_pct:
                zone = "ORANGE"
                warning_level = 3
                action = "SOFT_WARNING_3_HALT_NEW_RISK"
            elif max_util_pct >= self.soft_warning_2_pct:
                zone = "YELLOW"
                warning_level = 2
                action = "SOFT_WARNING_2_REDUCE_LOTS"
            elif max_util_pct >= self.soft_warning_1_pct:
                zone = "YELLOW"
                warning_level = 1
                action = "SOFT_WARNING_1_NOTIFY"
            return {
                "zone": zone,
                "warning_level": warning_level,
                "action": action,
                "current_equity": round(current_equity, 2),
                "peak_equity": round(self.peak_equity, 2),
                "daily_loss_pct": round(max(0.0, daily_loss_pct), 2),
                "trailing_dd_pct": round(max(0.0, trailing_dd_pct), 2),
                "max_utilization_pct": round(max(0.0, max_util_pct), 2),
                "is_locked_out": zone == "RED",
            }
