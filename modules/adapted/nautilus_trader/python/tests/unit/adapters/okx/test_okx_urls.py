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
Test okx urls behavior.
"""

import pytest
from nautilus_trader.adapters.okx import (
    OKXDataClientConfig,
    OKXEnvironment,
    OKXExecutionClientConfig,
    OKXRegion,
    get_okx_http_base_url,
    get_okx_ws_url_business,
    get_okx_ws_url_private,
    get_okx_ws_url_public,
)
from nautilus_trader.model import AccountId


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        (OKXRegion.GLOBAL, "https://www.okx.com"),
        (OKXRegion.EEA, "https://eea.okx.com"),
        (OKXRegion.US, "https://us.okx.com"),
    ],
)
def test_http_base_url_by_region(region: OKXRegion, expected: str) -> None:
    """
    Test http base url by region.
    """
    assert get_okx_http_base_url(region) == expected


def test_http_base_url_defaults_to_global() -> None:
    """
    Test http base url defaults to global.
    """
    assert get_okx_http_base_url() == "https://www.okx.com"


@pytest.mark.parametrize(
    ("region", "public", "private", "business"),
    [
        (
            OKXRegion.GLOBAL,
            "wss://ws.okx.com:8443/ws/v5/public",
            "wss://ws.okx.com:8443/ws/v5/private",
            "wss://ws.okx.com:8443/ws/v5/business",
        ),
        (
            OKXRegion.EEA,
            "wss://wseea.okx.com:8443/ws/v5/public",
            "wss://wseea.okx.com:8443/ws/v5/private",
            "wss://wseea.okx.com:8443/ws/v5/business",
        ),
        (
            OKXRegion.US,
            "wss://wsus.okx.com:8443/ws/v5/public",
            "wss://wsus.okx.com:8443/ws/v5/private",
            "wss://wsus.okx.com:8443/ws/v5/business",
        ),
    ],
)
def test_ws_urls_by_region_live(
    region: OKXRegion,
    public: str,
    private: str,
    business: str,
) -> None:
    """
    Test ws urls by region live.
    """
    assert get_okx_ws_url_public(OKXEnvironment.LIVE, region) == public
    assert get_okx_ws_url_private(OKXEnvironment.LIVE, region) == private
    assert get_okx_ws_url_business(OKXEnvironment.LIVE, region) == business


def test_ws_urls_eea_demo() -> None:
    """
    Test ws urls eea demo.
    """
    assert (
        get_okx_ws_url_public(OKXEnvironment.DEMO, OKXRegion.EEA)
        == "wss://wseeapap.okx.com:8443/ws/v5/public"
    )


def test_data_config_defaults_to_global_region() -> None:
    """
    Test data config defaults to global region.
    """
    config = OKXDataClientConfig()

    assert config.region == OKXRegion.GLOBAL


def test_exec_config_accepts_region() -> None:
    """
    Test exec config accepts region.
    """
    config = OKXExecutionClientConfig(
        account_id=AccountId("OKX-001"),
        region=OKXRegion.EEA,
    )

    assert config.region == OKXRegion.EEA


def test_okx_region_enum_surface() -> None:
    """
    Test okx region enum surface.
    """
    # OKXRegion must mirror OKXEnvironment's surface so frozen configs with a region
    # field stay hashable, and string/TOML values round-trip.
    assert len({OKXRegion.GLOBAL, OKXRegion.EEA, OKXRegion.US}) == 3  # hashable + distinct
    assert OKXRegion.from_str("eea") == OKXRegion.EEA
    assert OKXRegion.from_str("EEA") == OKXRegion.EEA  # case-insensitive
    assert set(OKXRegion.variants()) == {"global", "eea", "us"}
