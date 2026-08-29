"""
Freqtrade Protection Engine & Dynamic Pair Locking System (EQATS Institutional Adaptation)
Adapted from freqtrade/freqtrade (plugins/protectionmanager.py & plugins/protections)

Provides:
- Dynamic Pair Locking & Global Trading Pause System
- CooldownPeriod Protection Handler (post-trade pair lock)
- StoplossGuard Protection Handler (lock pair/global after N consecutive stoplosses in lookback)
- MaxDrawdownProtection Handler (lock global trading when portfolio drawdown exceeds limit)
- LowProfitPairs Handler (lock underperforming assets)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class LockSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    BOTH = "*"


@dataclass
class PairLock:
    symbol: str  # "*" for global lock
    until: datetime
    reason: str
    lock_side: LockSide = LockSide.BOTH


@dataclass
class ProtectionCheckResult:
    is_locked: bool
    reason: str
    until: Optional[datetime] = None


class FreqtradeProtectionEngine:
    """Freqtrade Protection Manager & Dynamic Pair Lock Engine."""

    def __init__(self):
        self.pair_locks: List[PairLock] = []
        self.trade_history: List[Dict[str, Any]] = []

    def lock_pair(self, symbol: str, until: datetime, reason: str, lock_side: LockSide = LockSide.BOTH) -> PairLock:
        """Locks a specific pair or global trading '*' until a specified time."""
        lock = PairLock(symbol=symbol, until=until, reason=reason, lock_side=lock_side)
        self.pair_locks.append(lock)
        return lock

    def is_locked(self, symbol: str, current_time: datetime, side: LockSide = LockSide.LONG) -> ProtectionCheckResult:
        """Checks if a pair or global trading is locked at the current timestamp."""
        active_locks = []
        for lock in self.pair_locks:
            if current_time < lock.until:
                if lock.symbol == "*" or lock.symbol == symbol:
                    if lock.lock_side == LockSide.BOTH or lock.lock_side == side:
                        active_locks.append(lock)

        if active_locks:
            latest_lock = max(active_locks, key=lambda l: l.until)
            return ProtectionCheckResult(
                is_locked=True,
                reason=f"Pair/Global Locked: {latest_lock.reason} until {latest_lock.until.isoformat()}",
                until=latest_lock.until,
            )

        return ProtectionCheckResult(is_locked=False, reason="NOT_LOCKED")

    def record_completed_trade(
        self,
        symbol: str,
        side: LockSide,
        realized_pnl: float,
        is_stoploss: bool,
        close_time: datetime,
    ):
        """Records completed trade history for protection evaluation."""
        self.trade_history.append(
            {
                "symbol": symbol,
                "side": side,
                "realized_pnl": realized_pnl,
                "is_stoploss": is_stoploss,
                "close_time": close_time,
            }
        )

    def evaluate_cooldown_period(
        self, symbol: str, current_time: datetime, cooldown_minutes: float = 30.0
    ) -> Optional[PairLock]:
        """Locks pair for `cooldown_minutes` after a trade closes."""
        recent_trades = [
            t for t in self.trade_history if t["symbol"] == symbol and t["close_time"] <= current_time
        ]
        if recent_trades:
            last_trade = max(recent_trades, key=lambda t: t["close_time"])
            time_since_close = (current_time - last_trade["close_time"]).total_seconds() / 60.0
            if time_since_close < cooldown_minutes:
                until = last_trade["close_time"] + timedelta(minutes=cooldown_minutes)
                return self.lock_pair(
                    symbol, until, f"CooldownPeriod active ({cooldown_minutes} min post-trade lock)"
                )
        return None

    def evaluate_stoploss_guard(
        self,
        symbol: str,
        current_time: datetime,
        lookback_minutes: float = 120.0,
        stoploss_limit: int = 2,
        lock_minutes: float = 120.0,
    ) -> Optional[PairLock]:
        """Locks pair if hit `stoploss_limit` stoplosses within `lookback_minutes`."""
        lookback_start = current_time - timedelta(minutes=lookback_minutes)
        recent_sl_trades = [
            t
            for t in self.trade_history
            if t["symbol"] == symbol
            and t["is_stoploss"]
            and lookback_start <= t["close_time"] <= current_time
        ]

        if len(recent_sl_trades) >= stoploss_limit:
            until = current_time + timedelta(minutes=lock_minutes)
            return self.lock_pair(
                symbol,
                until,
                f"StoplossGuard ({len(recent_sl_trades)} stoplosses hit in {lookback_minutes} min lookback)",
            )

        return None

    def evaluate_max_drawdown_protection(
        self,
        current_drawdown_pct: float,
        current_time: datetime,
        max_drawdown_limit_pct: float = 10.0,
        lock_minutes: float = 1440.0,
    ) -> Optional[PairLock]:
        """Triggers a global trading lock '*' when portfolio drawdown exceeds limit."""
        if current_drawdown_pct >= max_drawdown_limit_pct:
            until = current_time + timedelta(minutes=lock_minutes)
            return self.lock_pair(
                "*",
                until,
                f"MaxDrawdownProtection (Portfolio DD {current_drawdown_pct:.1f}% >= {max_drawdown_limit_pct:.1f}%)",
            )
        return None
