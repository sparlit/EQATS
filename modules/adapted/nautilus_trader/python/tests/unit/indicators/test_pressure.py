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
Test constructor validation for indicators composed from ATR and Keltner channels.
"""

import pytest
from nautilus_trader.indicators import KeltnerPosition, Pressure


def test_pressure_negative_atr_floor_raises_value_error() -> None:
    """
    Test a negative ATR floor raises ValueError instead of panicking.
    """
    with pytest.raises(ValueError, match="value_floor"):
        Pressure(10, atr_floor=-1.0)


def test_pressure_zero_period_raises_value_error() -> None:
    """
    Test a zero period raises ValueError instead of panicking.
    """
    with pytest.raises(ValueError, match="period must be > 0"):
        Pressure(0)


@pytest.mark.parametrize("k_multiplier", [0.0, -1.0])
def test_keltner_position_non_positive_multiplier_raises_value_error(k_multiplier: float) -> None:
    """
    Test a non-positive multiplier raises ValueError instead of panicking.
    """
    with pytest.raises(ValueError, match="k_multiplier must be finite and positive"):
        KeltnerPosition(10, k_multiplier)


def test_keltner_position_negative_atr_floor_raises_value_error() -> None:
    """
    Test a negative ATR floor raises ValueError instead of panicking.
    """
    with pytest.raises(ValueError, match="value_floor"):
        KeltnerPosition(10, 2.0, atr_floor=-1.0)
