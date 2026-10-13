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
Test example configs behavior.
"""

import pytest
from nautilus_trader.model import BarType, ClientId, InstrumentId, Quantity, StrategyId
from nautilus_trader.trading import (
    CompositeMarketMakerConfig,
    DeltaNeutralVolConfig,
    EmaCrossConfig,
    GridMarketMakerConfig,
    HurstVpinDirectionalConfig,
)

INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT.BINANCE")
SIGNAL_INSTRUMENT_ID = InstrumentId.from_str("ETHUSDT.BINANCE")
STRATEGY_ID = StrategyId("EXAMPLE-001")
ORDER_ID_TAG = "001"


@pytest.mark.parametrize(
    "config",
    [
        CompositeMarketMakerConfig(
            instrument_id=INSTRUMENT_ID,
            signal_instrument_id=SIGNAL_INSTRUMENT_ID,
            max_position=Quantity.from_str("1"),
            strategy_id=STRATEGY_ID,
            order_id_tag=ORDER_ID_TAG,
        ),
        DeltaNeutralVolConfig(
            option_family="BTC",
            hedge_instrument_id=INSTRUMENT_ID,
            client_id=ClientId("EXEC-001"),
            strategy_id=STRATEGY_ID,
            order_id_tag=ORDER_ID_TAG,
        ),
        EmaCrossConfig(
            instrument_id=INSTRUMENT_ID,
            trade_size=Quantity.from_str("1"),
            strategy_id=STRATEGY_ID,
            order_id_tag=ORDER_ID_TAG,
        ),
        GridMarketMakerConfig(
            instrument_id=INSTRUMENT_ID,
            max_position=Quantity.from_str("1"),
            strategy_id=STRATEGY_ID,
            order_id_tag=ORDER_ID_TAG,
        ),
        HurstVpinDirectionalConfig(
            instrument_id=INSTRUMENT_ID,
            bar_type=BarType.from_str("BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL"),
            trade_size=Quantity.from_str("1"),
            strategy_id=STRATEGY_ID,
            order_id_tag=ORDER_ID_TAG,
        ),
    ],
)
def test_example_strategy_config_base_readback(config: object) -> None:
    """
    Test example strategy config base readback.
    """
    assert config.strategy_id == STRATEGY_ID
    assert config.order_id_tag == ORDER_ID_TAG


def test_delta_neutral_vol_config_iv_param_key_readback() -> None:
    """
    Test delta neutral vol config iv param key readback.
    """
    config = DeltaNeutralVolConfig(
        option_family="BTC",
        hedge_instrument_id=INSTRUMENT_ID,
        client_id=ClientId("EXEC-001"),
        iv_param_key="mark_iv",
    )

    assert config.iv_param_key == "mark_iv"


def test_grid_market_maker_config_client_order_id_settings() -> None:
    """
    Test grid market maker config client order id settings.
    """
    config = GridMarketMakerConfig(
        instrument_id=INSTRUMENT_ID,
        max_position=Quantity.from_str("1"),
        use_uuid_client_order_ids=True,
        use_hyphens_in_client_order_ids=False,
    )

    assert config.use_uuid_client_order_ids is True
    assert config.use_hyphens_in_client_order_ids is False


def test_grid_market_maker_config_client_order_id_defaults() -> None:
    """
    Test grid market maker config client order id defaults.
    """
    config = GridMarketMakerConfig(
        instrument_id=INSTRUMENT_ID,
        max_position=Quantity.from_str("1"),
    )

    assert config.use_uuid_client_order_ids is False
    assert config.use_hyphens_in_client_order_ids is True
