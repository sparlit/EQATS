"""
StockSharp Extensible Risk Control Manager (EQATS Institutional Adaptation)
Adapted from StockSharp/StockSharp (Algo/Risk module)

Provides:
- StockSharpRiskManager: Extensible Risk Rule Evaluator
- Modular Risk Rules:
  - RiskPnLRule: Unrealized/Realized PnL loss threshold enforcement
  - RiskOrderFreqRule: Order submission rate limiting per time window
  - RiskOrderVolumeRule: Single order volume cap
  - RiskSlippageRule: Maximum slippage tolerance cap
  - RiskErrorRule: Order error rejection rate limiter
- Risk Actions: CLOSE_POSITIONS, CANCEL_ORDERS, STOP_TRADING
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

class RiskAction(str, Enum):
    NONE = 'NONE'
    CANCEL_ORDERS = 'CANCEL_ORDERS'
    CLOSE_POSITIONS = 'CLOSE_POSITIONS'
    STOP_TRADING = 'STOP_TRADING'

@dataclass
class RiskRuleViolation:
    rule_name: str
    message: str
    action: RiskAction
    timestamp: datetime

class StockSharpRiskManager:
    """StockSharp Extensible Risk Control Manager Engine."""

    def __init__(self, max_realized_loss_usd: float=2000.0, max_unrealized_loss_usd: float=1500.0, max_orders_per_minute: int=20, max_order_volume: float=10.0, max_slippage_pips: float=5.0, max_consecutive_errors: int=3) -> None:
        self.max_realized_loss_usd = max_realized_loss_usd
        self.max_unrealized_loss_usd = max_unrealized_loss_usd
        self.max_orders_per_minute = max_orders_per_minute
        self.max_order_volume = max_order_volume
        self.max_slippage_pips = max_slippage_pips
        self.max_consecutive_errors = max_consecutive_errors
        self.order_timestamps: List[datetime] = []
        self.consecutive_errors: int = 0
        self.violations: List[RiskRuleViolation] = []

    def evaluate_order(self, volume: float, current_time: datetime) -> List[RiskRuleViolation]:
        """Evaluates pre-order volume and frequency submission rules."""
        rule_violations = []
        if volume > self.max_order_volume:
            violation = RiskRuleViolation(rule_name='RiskOrderVolumeRule', message=f'Order volume {volume:.2f} exceeds cap {self.max_order_volume:.2f}', action=RiskAction.CANCEL_ORDERS, timestamp=current_time)
            rule_violations.append(violation)
        minute_ago = current_time - timedelta(minutes=1)
        recent_orders = [t for t in self.order_timestamps if t >= minute_ago]
        if len(recent_orders) >= self.max_orders_per_minute:
            violation = RiskRuleViolation(rule_name='RiskOrderFreqRule', message=f'Order rate {len(recent_orders)}/min exceeds frequency limit {self.max_orders_per_minute}/min', action=RiskAction.STOP_TRADING, timestamp=current_time)
            rule_violations.append(violation)
        if not rule_violations:
            self.order_timestamps.append(current_time)
        self.violations.extend(rule_violations)
        return rule_violations

    def evaluate_pnl_rule(self, realized_pnl: float, unrealized_pnl: float, current_time: datetime) -> List[RiskRuleViolation]:
        """Evaluates realized and unrealized portfolio PnL loss rules."""
        rule_violations = []
        if realized_pnl <= -self.max_realized_loss_usd:
            violation = RiskRuleViolation(rule_name='RiskPnLRule_Realized', message=f'Realized loss ${abs(realized_pnl):,.2f} >= ${self.max_realized_loss_usd:,.2f} limit', action=RiskAction.STOP_TRADING, timestamp=current_time)
            rule_violations.append(violation)
        if unrealized_pnl <= -self.max_unrealized_loss_usd:
            violation = RiskRuleViolation(rule_name='RiskPnLRule_Unrealized', message=f'Unrealized loss ${abs(unrealized_pnl):,.2f} >= ${self.max_unrealized_loss_usd:,.2f} limit', action=RiskAction.CLOSE_POSITIONS, timestamp=current_time)
            rule_violations.append(violation)
        self.violations.extend(rule_violations)
        return rule_violations

    def evaluate_slippage_rule(self, actual_slippage_pips: float, current_time: datetime) -> List[RiskRuleViolation]:
        """Evaluates order execution slippage rule."""
        rule_violations = []
        if actual_slippage_pips > self.max_slippage_pips:
            violation = RiskRuleViolation(rule_name='RiskSlippageRule', message=f'Slippage {actual_slippage_pips:.1f} pips > {self.max_slippage_pips:.1f} pips limit', action=RiskAction.CANCEL_ORDERS, timestamp=current_time)
            rule_violations.append(violation)
        self.violations.extend(rule_violations)
        return rule_violations

    def record_order_error(self, current_time: datetime) -> List[RiskRuleViolation]:
        """Records order rejection error and triggers RiskErrorRule if error count exceeded."""
        self.consecutive_errors += 1
        rule_violations = []
        if self.consecutive_errors >= self.max_consecutive_errors:
            violation = RiskRuleViolation(rule_name='RiskErrorRule', message=f'Consecutive errors {self.consecutive_errors} >= {self.max_consecutive_errors} limit', action=RiskAction.STOP_TRADING, timestamp=current_time)
            rule_violations.append(violation)
        self.violations.extend(rule_violations)
        return rule_violations

    def record_order_success(self) -> None:
        """Resets consecutive error counter on successful order fill."""
        self.consecutive_errors = 0
