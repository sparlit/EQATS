from __future__ import annotations

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


"""Deterministic capital allocation rules for the V2 paper portfolio.

These settings are explicit system defaults, not broker instructions.  Every
position remains a research recommendation until the user enters it manually.
"""

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class PortfolioConfig:
    capital_base: float = 300_000.0
    risk_per_trade_pct: float = 0.01
    max_position_pct: float = 0.20
    max_portfolio_risk_pct: float = 0.05
    max_open_positions: int = 8

    @property
    def risk_budget_per_trade(self) -> float:
        return self.capital_base * self.risk_per_trade_pct

    @property
    def max_position_value(self) -> float:
        return self.capital_base * self.max_position_pct

    @property
    def max_portfolio_risk(self) -> float:
        return self.capital_base * self.max_portfolio_risk_pct


@dataclass(frozen=True)
class Allocation:
    quantity: int
    entry_notional: float
    initial_risk: float
    binding_constraint: str


def allocate_long_position(
    entry: float,
    stop: float,
    *,
    committed_capital: float,
    committed_risk: float,
    committed_positions: int,
    config: PortfolioConfig = PortfolioConfig(),
) -> Allocation:
    """Size a long by the tightest of risk, position, portfolio and cash caps."""
    if entry <= stop or stop <= 0:
        msg = "long allocation requires entry > stop > 0"
        raise ValueError(msg)
    if committed_positions >= config.max_open_positions:
        return Allocation(0, 0.0, 0.0, "max_open_positions")
    cash_capacity = max(0.0, config.capital_base - committed_capital)
    risk_capacity = max(0.0, config.max_portfolio_risk - committed_risk)
    per_share_risk = entry - stop
    limits = {
        "risk_budget_per_trade": floor(config.risk_budget_per_trade / per_share_risk),
        "max_position_value": floor(config.max_position_value / entry),
        "remaining_capital": floor(cash_capacity / entry),
        "remaining_portfolio_risk": floor(risk_capacity / per_share_risk),
    }
    quantity = max(0, min(limits.values()))
    binding = min(limits, key=limits.get)
    return Allocation(
        quantity=quantity,
        entry_notional=round(quantity * entry, 2),
        initial_risk=round(quantity * per_share_risk, 2),
        binding_constraint=binding,
    )
