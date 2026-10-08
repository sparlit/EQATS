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
Test inspection behavior.
"""

import pytest
from nautilus_trader.indicators import (
    AdaptiveMovingAverage,
    DoubleExponentialMovingAverage,
    ExponentialMovingAverage,
    HullMovingAverage,
    SimpleMovingAverage,
    SpreadAnalyzer,
    VariableIndexDynamicAverage,
    WeightedMovingAverage,
    WilderMovingAverage,
)
from nautilus_trader.model import InstrumentId, PriceType


def test_adaptive_moving_average_inspection_properties() -> None:
    """
    Test adaptive moving average inspection properties.
    """
    indicator = AdaptiveMovingAverage(
        period_efficiency_ratio=10,
        period_fast=2,
        period_slow=30,
        price_type=PriceType.MID,
    )

    for _ in range(11):
        indicator.update_raw(12.5)

    assert indicator.period_efficiency_ratio == 10
    assert indicator.period_fast == 2
    assert indicator.period_slow == 30
    assert indicator.alpha_fast == pytest.approx(2 / 3)
    assert indicator.alpha_slow == pytest.approx(2 / 31)
    assert indicator.alpha_diff == pytest.approx((2 / 3) - (2 / 31))
    assert indicator.price_type == PriceType.MID
    assert indicator.value == 12.5


def test_weighted_moving_average_inspection_properties() -> None:
    """
    Test weighted moving average inspection properties.
    """
    indicator = WeightedMovingAverage(
        period=3,
        weights=[0.2, 0.3, 0.5],
        price_type=PriceType.BID,
    )

    for _ in range(3):
        indicator.update_raw(12.5)

    assert indicator.price_type == PriceType.BID
    assert indicator.value == 12.5
    assert indicator.weights == [0.2, 0.3, 0.5]


def test_spread_analyzer_instrument_id_readback() -> None:
    """
    Test spread analyzer instrument id readback.
    """
    instrument_id = InstrumentId.from_str("AUD/USD.SIM")
    indicator = SpreadAnalyzer(instrument_id=instrument_id, capacity=10)

    assert indicator.instrument_id == instrument_id


@pytest.mark.parametrize(
    "indicator_type",
    [
        DoubleExponentialMovingAverage,
        ExponentialMovingAverage,
        HullMovingAverage,
        SimpleMovingAverage,
        VariableIndexDynamicAverage,
        WilderMovingAverage,
    ],
)
def test_moving_average_price_type_readback(indicator_type: object) -> None:
    """
    Test moving average price type readback.
    """
    indicator = indicator_type(period=10, price_type=PriceType.ASK)

    assert indicator.price_type == PriceType.ASK
