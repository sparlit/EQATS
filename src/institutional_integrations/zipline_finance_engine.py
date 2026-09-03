"""
Zipline Slippage, Commission & Execution Control Engine (EQATS Institutional Adaptation)
Adapted from quantopian/zipline (zipline/finance/slippage.py, commission.py, controls.py)

Provides:
- ZiplineSlippageModel:
  - VolumeShareSlippage: Market impact model based on order volume share relative to total bar volume
  - FixedSlippage: Constant spread or pip offset
- ZiplineCommissionModel:
  - PerUnitCommission: Fee charged per contract or share
  - PerDollarCommission: Fee charged as a percentage of total transaction value
  - PerTradeCommission: Fixed minimum cost per executed trade order
- ZiplineRiskControlEngine:
  - MaxLeverageControl: Verifies portfolio leverage bounds
  - MaxPositionSizeControl: Limits maximum size per single position
  - MinMaxOrderValueControl: Enforces minimum and maximum order value bounds
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class SlippageResult:
    original_price: float
    fill_price: float
    slippage_cost_usd: float
    volume_share: float


@dataclass
class CommissionResult:
    commission_usd: float
    fee_per_unit: float


@dataclass
class RiskControlCheck:
    passed: bool
    violations: list[str]


class ZiplineSlippageModel:
    """Zipline Market Impact & Volume Share Slippage Engine."""

    def __init__(
        self,
        volume_limit_pct: float = 0.025,
        price_impact_factor: float = 0.1,
        fixed_spread_pips: float = 0.0,
        pip_size: float = 0.0001,
    ) -> None:
        self.volume_limit_pct = volume_limit_pct
        self.price_impact_factor = price_impact_factor
        self.fixed_spread_pips = fixed_spread_pips
        self.pip_size = pip_size

    def calculate_volume_share_slippage(
        self, order_quantity: float, bar_volume: float, bar_price: float, side: OrderSide,
    ) -> SlippageResult:
        """Calculates volume share market impact fill price."""
        if bar_volume <= 0 or order_quantity <= 0:
            return SlippageResult(bar_price, bar_price, 0.0, 0.0)
        volume_share = min(self.volume_limit_pct, order_quantity / float(bar_volume))
        impact = bar_price * (self.price_impact_factor * volume_share**2)
        fill_price = bar_price + impact if side == OrderSide.BUY else bar_price - impact
        slippage_cost = abs(fill_price - bar_price) * order_quantity
        return SlippageResult(
            original_price=bar_price,
            fill_price=round(fill_price, 5),
            slippage_cost_usd=round(slippage_cost, 2),
            volume_share=volume_share,
        )

    def calculate_fixed_slippage(
        self, bar_price: float, side: OrderSide, order_quantity: float = 1.0,
    ) -> SlippageResult:
        """Calculates fixed spread/pip offset fill price."""
        offset = self.fixed_spread_pips * self.pip_size
        fill_price = bar_price + offset if side == OrderSide.BUY else bar_price - offset
        slippage_cost = offset * order_quantity
        return SlippageResult(
            original_price=bar_price,
            fill_price=round(fill_price, 5),
            slippage_cost_usd=round(slippage_cost, 2),
            volume_share=0.0,
        )


class ZiplineCommissionModel:
    """Zipline Trade Commission Model Engine."""

    def per_unit(self, quantity: float, cost_per_unit: float = 0.001) -> CommissionResult:
        """Calculates commission based on fixed cost per unit/share."""
        fee = abs(quantity) * cost_per_unit
        return CommissionResult(commission_usd=round(fee, 2), fee_per_unit=cost_per_unit)

    def per_dollar(self, transaction_value_usd: float, cost_per_dollar: float = 0.0015) -> CommissionResult:
        """Calculates commission as percentage of total dollar value."""
        fee = abs(transaction_value_usd) * cost_per_dollar
        return CommissionResult(commission_usd=round(fee, 2), fee_per_unit=cost_per_dollar)

    def per_trade(
        self,
        quantity: float,
        transaction_value_usd: float,
        cost_per_unit: float = 0.001,
        minimum_fee_per_trade: float = 1.0,
    ) -> CommissionResult:
        """Calculates unit fee with a guaranteed minimum fee per trade."""
        raw_fee = abs(quantity) * cost_per_unit
        fee = max(minimum_fee_per_trade, raw_fee)
        return CommissionResult(commission_usd=round(fee, 2), fee_per_unit=cost_per_unit)


class ZiplineRiskControlEngine:
    """Zipline Pre-Trade Risk Control & Limits Engine."""

    def __init__(
        self,
        max_leverage: float = 10.0,
        max_position_size_usd: float = 50000.0,
        min_order_value_usd: float = 10.0,
        max_order_value_usd: float = 25000.0,
    ) -> None:
        self.max_leverage = max_leverage
        self.max_position_size_usd = max_position_size_usd
        self.min_order_value_usd = min_order_value_usd
        self.max_order_value_usd = max_order_value_usd

    def check_pre_trade_controls(
        self, order_value_usd: float, current_portfolio_exposure_usd: float, account_equity: float,
    ) -> RiskControlCheck:
        """Validates proposed order against Zipline leverage and order value controls."""
        violations = []
        if order_value_usd < self.min_order_value_usd:
            violations.append(f"Order value ${order_value_usd:,.2f} < ${self.min_order_value_usd:,.2f} min threshold")
        if order_value_usd > self.max_order_value_usd:
            violations.append(f"Order value ${order_value_usd:,.2f} > ${self.max_order_value_usd:,.2f} max limit")
        new_exposure = current_portfolio_exposure_usd + order_value_usd
        new_leverage = new_exposure / account_equity if account_equity > 0 else 0.0
        if new_leverage > self.max_leverage:
            violations.append(f"Proposed leverage {new_leverage:.2f}x exceeds max limit {self.max_leverage:.2f}x")
        if order_value_usd > self.max_position_size_usd:
            violations.append(f"Position value ${order_value_usd:,.2f} exceeds cap ${self.max_position_size_usd:,.2f}")
        return RiskControlCheck(passed=len(violations) == 0, violations=violations)
