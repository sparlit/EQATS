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


from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class StrategyResult:
    strategy_name: str
    weights: pd.DataFrame
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class StrategyConfig:
    name: str = "BaseStrategy"


class BaseStrategy:
    """Minimal base strategy interface."""

    def __init__(self, config: StrategyConfig):
        self.config = config

    def generate_weights(self, data: dict[str, pd.DataFrame], target_date: str | None = None) -> StrategyResult:
        msg = "generate_weights must be implemented by subclasses"
        raise NotImplementedError(msg)


class EqualWeightStrategy(BaseStrategy):
    """A strategy class that gives equal weight to all stocks"""

    def generate_weights(self, data: dict[str, pd.DataFrame], target_date: str | None = None) -> StrategyResult:
        tickers = data["fundamentals"]["gvkey"].unique()
        weight = 1.0 / len(tickers)
        weights_df = pd.DataFrame({"gvkey": tickers, "weight": [weight] * len(tickers)})
        return StrategyResult(strategy_name=self.config.name, weights=weights_df)


def create_strategy(strategy_type, config):
    strategies = {
        "equal_weight": EqualWeightStrategy,
    }

    strategy_class = strategies.get(strategy_type)
    if strategy_class is None:
        msg = f"Unknown strategy type: {strategy_type}"
        raise ValueError(msg)
    return strategy_class(config)
