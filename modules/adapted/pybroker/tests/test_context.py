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


"""Unit tests for context.py module."""

"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""

import re
from collections import deque
from decimal import Decimal

import numpy as np
import pytest
from pybroker.common import PriceType, StopType, to_datetime
from pybroker.config import StrategyConfig
from pybroker.context import (
    ExecContext,
    IntervalContext,
    set_exec_ctx_data,
)
from pybroker.portfolio import Order, Portfolio, Position, Trade

from .fixtures import *


@pytest.fixture
def portfolio():
    return Portfolio(100_000)


@pytest.fixture
def end_index():
    return 100


@pytest.fixture
def sym_end_index(symbols, end_index):
    return dict.fromkeys(symbols, end_index)


@pytest.fixture
def session():
    return {"foo": 1, "bar": 2}


@pytest.fixture
def foreign(symbols):
    return list(symbols)[-1]


@pytest.fixture
def date(dates, end_index):
    return list(dates)[end_index - 1]


@pytest.fixture
def orders(dates, symbols):
    return (
        Order(
            id=1,
            type="buy",
            symbol=symbols[1],
            date=dates[0],
            created=None,
            order_type="market",
            intent="buy_to_open",
            shares=Decimal(200),
            limit_price=None,
            market_price=Decimal(10),
            fill_price=Decimal(10),
            fees=Decimal(0),
        ),
        Order(
            id=2,
            type="sell",
            symbol=symbols[2],
            date=dates[1],
            created=None,
            order_type="market",
            intent="sell_to_open",
            shares=Decimal(100),
            limit_price=Decimal(100),
            market_price=Decimal("101.1"),
            fill_price=Decimal("101.1"),
            fees=Decimal(0),
        ),
    )


@pytest.fixture
def trades(dates, symbols):
    return Trade(
        id=1,
        type="long",
        symbol=symbols[-1],
        entry_date=dates[0],
        exit_date=dates[1],
        entry=100,
        exit=101,
        shares=100,
        pnl=Decimal(100),
        return_pct=Decimal(100),
    )
