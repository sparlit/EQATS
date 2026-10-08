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


# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Test conftest behavior.
"""

import gc
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from nautilus_trader.common import LogLevel, init_logging
from nautilus_trader.core import UUID4
from nautilus_trader.model import AccountId, Currency, InstrumentId, StrategyId, TraderId, Venue

# Run allocation tracking separately with make pytest-memray
collect_ignore = ["memleak"]


# Add tests/ to sys.path so test strategies are importable by the engine
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


def pytest_addoption(parser) -> None:
    """
    Expose the extended client runtime stress workload.
    """
    parser.addoption(
        "--client-runtime-stress",
        action="store_true",
        help="Run eight lifetimes per client runtime stress case instead of two",
    )


@pytest.fixture(scope="session", autouse=True)
def bypass_logging() -> object:
    """
    Fixture to bypass logging for all tests.

    `autouse=True` will mean this function is run prior to every test. To disable this
    to debug specific tests, simply comment this out.

    """
    return init_logging(
        trader_id=TraderId("TESTER-000"),
        instance_id=UUID4(),
        level_stdout=LogLevel.DEBUG,
        is_bypassed=True,
        print_config=False,
    )


@pytest.fixture
def trader_id() -> object:
    """
    Trader id.
    """
    return TraderId("TRADER-001")


@pytest.fixture
def strategy_id() -> object:
    """
    Strategy id.
    """
    return StrategyId("S-001")


@pytest.fixture
def account_id() -> object:
    """
    Account id.
    """
    return AccountId("SIM-000")


@pytest.fixture
def venue() -> object:
    """
    Venue.
    """
    return Venue("SIM")


@pytest.fixture
def usd() -> object:
    """
    Usd.
    """
    return Currency.from_str("USD")


@pytest.fixture
def btc() -> object:
    """
    Btc.
    """
    return Currency.from_str("BTC")


@pytest.fixture
def usdt() -> object:
    """
    Usdt.
    """
    return Currency.from_str("USDT")


@pytest.fixture
def audusd_id() -> object:
    """
    Audusd id.
    """
    return InstrumentId.from_str("AUD/USD.SIM")


@pytest.fixture
def usdjpy_id() -> object:
    """
    Usdjpy id.
    """
    return InstrumentId.from_str("USD/JPY.SIM")


@pytest.fixture
def collect_node_cycles() -> Iterator[None]:
    """
    Collect unreachable node reference cycles after each test.
    """
    yield
    gc.collect()
