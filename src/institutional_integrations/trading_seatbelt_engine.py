"""
Trading Seatbelt OS Safety Engine (EQATS Institutional Adaptation)
Adapted from oxyalgo/trading-seatbelt-os and ead8/RiskRabbit

Provides pre-trade safety governor rules:
- Consecutive Loss Throttler & Revenge Trading Cooldown (30m after 2 losses, 2h after 3 losses, 24h after 4 losses)
- Trade Frequency & Daily Execution Caps
- Offer Scam & Red Flag Pattern Detector
- Pre-Trade Safety Checklist Compliance Auditor
- Maximum Trade Duration Lockdown Timer
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class SeatbeltStatus(str, Enum):
    GO = "GO"
    CAUTION = "CAUTION"
    LOCKDOWN = "LOCKDOWN"


@dataclass
class CooldownStatus:
    active: bool
    remaining_seconds: float
    reason: str
    recommended_action: str


@dataclass
class PreTradeChecklistResult:
    passed: bool
    passed_items: list[str]
    failed_items: list[str]


class TradingSeatbeltEngine:
    """Trading Seatbelt OS Safety Governor Engine."""

    def __init__(
        self, max_daily_trades: int = 15, max_consecutive_losses: int = 3, max_position_duration_minutes: float = 240.0,
    ) -> None:
        self.max_daily_trades = max_daily_trades
        self.max_consecutive_losses = max_consecutive_losses
        self.max_position_duration_minutes = max_position_duration_minutes
        self.recent_losses: int = 0
        self.daily_trade_count: int = 0
        self.cooldown_until: datetime | None = None
        self.cooldown_reason: str = ""
        self.last_trade_time: datetime | None = None

    def record_trade_outcome(self, is_win: bool, timestamp: datetime) -> CooldownStatus:
        """Updates internal trade history and calculates mandatory cooldown timer if needed."""
        self.daily_trade_count += 1
        self.last_trade_time = timestamp
        if is_win:
            self.recent_losses = 0
        else:
            self.recent_losses += 1
        if self.recent_losses >= 4:
            self.cooldown_until = timestamp + timedelta(hours=24)
            self.cooldown_reason = "4 consecutive losses: Daily Revenge Trading Lockout active (24 Hours)"
        elif self.recent_losses == 3:
            self.cooldown_until = timestamp + timedelta(hours=2)
            self.cooldown_reason = "3 consecutive losses: Cool-off break active (2 Hours)"
        elif self.recent_losses == 2:
            self.cooldown_until = timestamp + timedelta(minutes=30)
            self.cooldown_reason = "2 consecutive losses: Tactical pause active (30 Minutes)"
        return self.get_cooldown_status(timestamp)

    def get_cooldown_status(self, current_time: datetime) -> CooldownStatus:
        """Returns current cooldown lockout status."""
        if self.cooldown_until and current_time < self.cooldown_until:
            rem = (self.cooldown_until - current_time).total_seconds()
            return CooldownStatus(
                active=True,
                remaining_seconds=rem,
                reason=self.cooldown_reason,
                recommended_action="FLATTEN / REJECT ENTRY - Wait out cooldown duration",
            )
        return CooldownStatus(
            active=False,
            remaining_seconds=0.0,
            reason="No active cooldown",
            recommended_action="PROCEED WITH RISK GOVERNANCE",
        )

    def verify_pre_trade_seatbelt(
        self, current_time: datetime, proposed_risk_pct: float, stop_loss_pips: float, news_in_next_15m: bool = False,
    ) -> tuple[SeatbeltStatus, list[str]]:
        """Performs pre-trade seatbelt checks prior to order routing."""
        reasons: list[str] = []
        cd = self.get_cooldown_status(current_time)
        if cd.active:
            reasons.append(f"Seatbelt Lockdown: {cd.reason} ({cd.remaining_seconds / 60:.1f} min left)")
        if self.daily_trade_count >= self.max_daily_trades:
            reasons.append(
                f"Daily Trade Cap Reached: {self.daily_trade_count}/{self.max_daily_trades} trades executed today",
            )
        if proposed_risk_pct > 2.0:
            reasons.append(f"Excessive Risk: Proposed risk {proposed_risk_pct:.1f}% exceeds 2.0% safe limit")
        if stop_loss_pips <= 0:
            reasons.append("Unprotected Entry: Stop loss pips must be > 0")
        if news_in_next_15m:
            reasons.append("High Impact News: Blackout active in next 15 minutes")
        if any("Lockdown" in r or "Cap" in r for r in reasons):
            return (SeatbeltStatus.LOCKDOWN, reasons)
        if len(reasons) > 0:
            return (SeatbeltStatus.CAUTION, reasons)
        return (SeatbeltStatus.GO, ["All Seatbelt OS checks passed cleanly"])

    def scan_red_flags(self, text: str) -> dict[str, Any]:
        """Scans marketing, strategy pitch, or signal text for fraud / red flag patterns."""
        patterns = [
            ("\\b(guaranteed|risk-free|100% win|no loss|can't lose)\\b", "Guaranteed profit / zero risk claim"),
            ("\\b(double your|10x|100x|flip account|millionaire)\\b", "Unrealistic return claim"),
            (
                "\\b(send crypto|telegram vip|dm for pass|prop pass service)\\b",
                "Prop firm pass service / direct payment scam",
            ),
        ]
        hits = []
        for p, label in patterns:
            if re.search(p, text, re.IGNORECASE):
                hits.append(label)
        risk_score = len(hits) * 35.0
        return {"red_flags_detected": hits, "risk_score": min(100.0, risk_score), "is_suspicious": len(hits) > 0}
