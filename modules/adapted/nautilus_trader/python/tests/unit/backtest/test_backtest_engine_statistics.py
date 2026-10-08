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
Test backtest engine statistics behavior.
"""

import math
from decimal import Decimal

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, Currency, Money, OmsType, Venue


def _float_maps_equal(a: dict[str, float], b: dict[str, float]) -> bool:
    """
    Return True if two str->float dicts are equal, treating NaN as equal to NaN.
    """
    if a.keys() != b.keys():
        return False
    for key in a:
        va, vb = a[key], b[key]
        if math.isnan(va) and math.isnan(vb):
            continue
        if va != vb:
            return False
    return True


def _nested_float_maps_equal(
    a: dict[str, dict[str, float]],
    b: dict[str, dict[str, float]],
) -> bool:
    """
    Return True if two str->str->float dicts are equal, treating NaN as equal to NaN.
    """
    if a.keys() != b.keys():
        return False
    return all(_float_maps_equal(a[key], b[key]) for key in a)


def _engine_with_account() -> BacktestEngine:
    engine = BacktestEngine(BacktestEngineConfig(bypass_logging=True))
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=Currency.from_str("USD"),
        starting_balances=[Money(1_000_000.0, Currency.from_str("USD"))],
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal(0),
            taker_rate=Decimal(0),
        ),
    )
    return engine


def test_engine_exposes_portfolio_statistics() -> None:
    """
    Test engine exposes portfolio statistics.
    """
    engine = _engine_with_account()
    engine.run()
    stats = engine.portfolio.statistics()
    assert isinstance(stats.pnls, dict)
    assert isinstance(stats.returns, dict)
    assert isinstance(stats.general, dict)
    engine.dispose()


def test_engine_portfolio_statistics_equals_result() -> None:
    """
    Test engine portfolio statistics equals result.
    """
    engine = _engine_with_account()
    engine.run()
    stats = engine.portfolio.statistics()
    result = engine.get_result()
    assert _nested_float_maps_equal(stats.pnls, result.stats_pnls)
    assert _float_maps_equal(stats.returns, result.stats_returns)
    assert _float_maps_equal(stats.general, result.stats_general)
    engine.dispose()
