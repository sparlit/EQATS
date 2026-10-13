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
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Test v1 spreads behavior.
"""

from nautilus_trader.adapters.okx import OKXHttpClient


def test_http_client_exposes_generic_spread_execution_methods() -> None:
    """
    Test http client exposes generic spread execution methods.
    """
    assert hasattr(OKXHttpClient, "place_order")
    assert hasattr(OKXHttpClient, "cancel_order")
    assert hasattr(OKXHttpClient, "cancel_all_orders")
    assert hasattr(OKXHttpClient, "request_order_status_reports")
    assert hasattr(OKXHttpClient, "request_fill_reports")


def test_http_client_does_not_expose_spread_specific_execution_methods() -> None:
    """
    Test http client does not expose spread specific execution methods.
    """
    assert not hasattr(OKXHttpClient, "place_spread_order")
    assert not hasattr(OKXHttpClient, "cancel_spread_order")
    assert not hasattr(OKXHttpClient, "cancel_all_spread_orders")
    assert not hasattr(OKXHttpClient, "request_spread_order_status_reports")
    assert not hasattr(OKXHttpClient, "request_spread_fill_reports")
