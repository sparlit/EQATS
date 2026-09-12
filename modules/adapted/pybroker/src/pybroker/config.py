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


"""Contains configuration options."""

"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Union

from pybroker.common import BarData, FeeInfo, FeeMode, PositionMode, PriceType


@dataclass(frozen=True)
class StrategyConfig:
    """Configuration options for :class:`pybroker.strategy.Strategy`.

    Attributes:
        initial_cash: Starting cash of strategy.
        fee_mode: :class:`pybroker.common.FeeMode` for calculating brokerage
            fees. Supports one of:

            - ``ORDER_PERCENT``: Fee is a percentage of order amount.
            - ``PER_ORDER``: Fee is a constant amount per order.
            - ``PER_SHARE``: Fee is a constant amount per share in order.
            - ``Callable[[FeeInfo], Decimal]``: Fees are calculated using a
                custom ``Callable`` that is passed
                :class:`pybroker.common.FeeInfo`.
            - ``None``: Fees are disabled (default).
        fee_amount: Brokerage fee amount.
        enable_fractional_shares: Whether to enable trading fractional shares.
            Set to ``True`` for crypto trading. Defaults to ``False``.
        round_fill_price: Whether to round fill prices to the nearest cent.
            Defaults to ``True``.
        position_mode: Position mode for :class:`pybroker.strategy.Strategy`.
            Supports one of:

            - ``DEFAULT``: Long and short positions.
            - ``LONG_ONLY``: Long-only positions.
            - ``SHORT_ONLY``: Short-only positions.
        buy_delay: Number of bars before placing an order for a buy signal. The
            default value of ``1`` places a buy order on the next bar. Must be
            > ``0``.
        sell_delay: Number of bars before placing an order for a sell signal.
            The default value of ``1`` places a sell order on the next bar.
            Must be > ``0``.
        bootstrap_samples: Number of samples used to compute boostrap metrics.
            Defaults to ``10_000``.
        exit_on_last_bar: Whether to automatically exit any open positions
            on the last bar of data available for a symbol. Defaults to
            ``False``.
        exit_cover_fill_price: Fill price for covering an open short position
            when :attr:`.exit_on_last_bar` is ``True``. Defaults to
            :attr:`pybroker.common.PriceType.MIDDLE`.
        exit_sell_fill_price: Fill price for selling an open long position when
            :attr:`.exit_on_last_bar` is ``True``. Defaults to
            :attr:`pybroker.common.PriceType.MIDDLE`.
        bars_per_year: Number of observations per year that will be used to
            annualize evaluation metrics. For example, a value of ``252`` would
            be used to annualize the Sharpe Ratio for daily returns. Also sets
            the accrual period for :attr:`.interest_rate`, and is therefore
            required when ``interest_rate`` is set.
        return_signals: When ``True``, then bar data, indicator data, and model
            predictions are returned with
            :class:`pybroker.strategy.TestResult`. Signals contain
            base-timeframe values only; an interval-bound indicator or model
            appears only when ``'base'`` is included in its binding.
            Defaults to ``False``.
        return_stops: When ``True``, then stop values are returned with
            :class:`pybroker.strategy.TestResult`. Defaults to ``False``.
        round_test_result: When ``True``, round values in
            :class:`pybroker.strategy.TestResult` up to the nearest cent.
            Defaults to ``True``.
        leverage: Account leverage multiplier for buying power on long and
            short positions. Default ``1.0`` uses cash-only buying.
            ``2.0`` allows positions up to 2x equity. Must be ``>= 1.0``.
        interest_rate: Annual interest rate, in percent, applied to net cash
            balance (``cash - margin_loan``). Charges interest when net cash
            is negative and credits interest when net cash is positive.
            Accrues once per bar at ``interest_rate / bars_per_year``, so
            :attr:`.bars_per_year` is required when this is set.
            Defaults to ``0`` (disabled).
        record_portfolio_bars: When ``True``, append full
            :class:`pybroker.portfolio.PortfolioBar` snapshots to
            :attr:`pybroker.portfolio.Portfolio.bars` on every bar. When
            ``False`` (default), per-bar metrics are stored in a compact
            buffer used for :class:`pybroker.strategy.TestResult` and
            :class:`pybroker.eval.EvalMetrics`.
        record_position_bars: When ``True``, append full
            :class:`pybroker.portfolio.PositionBar` snapshots to
            :attr:`pybroker.portfolio.Portfolio.position_bars` on every bar.
            When ``False`` (default), :attr:`pybroker.strategy.TestResult.positions`
            is empty.
    """

    initial_cash: float = field(default=100_000)
    fee_mode: FeeMode | Callable[[FeeInfo], Decimal] | None = field(default=None)
    fee_amount: float = field(default=0)
    enable_fractional_shares: bool = field(default=False)
    round_fill_price: bool = field(default=True)
    position_mode: PositionMode = field(default=PositionMode.DEFAULT)
    max_long_positions: int | None = field(default=None)
    max_short_positions: int | None = field(default=None)
    buy_delay: int = field(default=1)
    sell_delay: int = field(default=1)
    bootstrap_samples: int = field(default=10_000)
    exit_on_last_bar: bool = field(default=False)
    exit_cover_fill_price: PriceType | Callable[[str, BarData], int | float | Decimal] = field(default=PriceType.MIDDLE)
    exit_sell_fill_price: PriceType | Callable[[str, BarData], int | float | Decimal] = field(default=PriceType.MIDDLE)
    bars_per_year: int | None = field(default=None)
    return_signals: bool = field(default=False)
    return_stops: bool = field(default=False)
    round_test_result: bool = field(default=True)
    leverage: float = field(default=1.0)
    interest_rate: float = field(default=0.0)
    record_portfolio_bars: bool = field(default=False)
    record_position_bars: bool = field(default=False)
