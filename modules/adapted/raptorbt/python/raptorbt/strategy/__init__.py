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


"""Class-based strategy contract for RaptorBT.

Strategies subclass :class:`Strategy`, override lifecycle hooks
(``on_start``, ``on_bar``, ``on_stop``) and order/position event hooks, and
emit order intents (:meth:`Strategy.enter`, :meth:`Strategy.close_position`).
The engine simulates fills and routes resulting events back into the hooks.

Run one with :func:`run_strategy_backtest`, which returns the same
``BacktestResult`` as the array-based runners.
"""

from raptorbt.strategy.base import Strategy
from raptorbt.strategy.config import StrategyConfig
from raptorbt.strategy.context import (
    Bar,
    CompositeBar,
    QuoteTick,
    StrategyContext,
    TradeTick,
)
from raptorbt.strategy.orders import ClosePosition, MarketOrder
from raptorbt.strategy.portfolio_runner import PortfolioContext, run_portfolio_strategy
from raptorbt.strategy.runner import run_strategy_backtest
from raptorbt.strategy.tick_runner import run_tick_strategy
from raptorbt.strategy.tick_stream import TickStrategyStream

__all__ = [
    "Bar",
    "ClosePosition",
    "CompositeBar",
    "MarketOrder",
    "PortfolioContext",
    "QuoteTick",
    "Strategy",
    "StrategyConfig",
    "StrategyContext",
    "TickStrategyStream",
    "TradeTick",
    "run_portfolio_strategy",
    "run_strategy_backtest",
    "run_tick_strategy",
]
