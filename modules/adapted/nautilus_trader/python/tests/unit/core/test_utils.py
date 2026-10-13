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
Test utils behavior.
"""

import pytest
from nautilus_trader.core import (
    NAUTILUS_USER_AGENT,
    NAUTILUS_VERSION,
    convert_to_snake_case,
    mask_api_key,
)


def test_version_constants_are_consistent() -> None:
    """
    Test version constants are consistent.
    """
    assert NAUTILUS_VERSION
    assert f"NautilusTrader/{NAUTILUS_VERSION}" == NAUTILUS_USER_AGENT


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("SomePascalCase", "some_pascal_case"),
        ("AnotherExample", "another_example"),
        ("someCamelCase", "some_camel_case"),
        ("yetAnotherExample", "yet_another_example"),
        ("some-kebab-case", "some_kebab_case"),
        ("dashed-word-example", "dashed_word_example"),
        ("already_snake_case", "already_snake_case"),
        ("no_change_needed", "no_change_needed"),
        ("UPPER_CASE_EXAMPLE", "upper_case_example"),
        ("ANOTHER_UPPER_CASE", "another_upper_case"),
        ("MiXeD_CaseExample", "mi_xe_d_case_example"),
        ("Another-OneHere", "another_one_here"),
        ("BSPOrderBookDelta", "bsp_order_book_delta"),
        ("OrderBookDelta", "order_book_delta"),
        ("TradeTick", "trade_tick"),
    ],
)
def test_convert_to_snake_case(value: object, expected: object) -> None:
    """
    Test convert to snake case.
    """
    assert convert_to_snake_case(value) == expected


def test_mask_api_key_masks_middle() -> None:
    """
    Test mask api key masks middle.
    """
    assert mask_api_key("sk-abc123xyz789") == "sk-a...z789"


def test_mask_api_key_short_key() -> None:
    """
    Test mask api key short key.
    """
    assert mask_api_key("abc") == "***"
