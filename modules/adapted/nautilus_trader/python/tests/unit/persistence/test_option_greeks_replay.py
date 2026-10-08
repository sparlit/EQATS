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
Test option greeks replay behavior.
"""

import os
from pathlib import Path

import pytest
from nautilus_trader.common import DataActor, DataActorConfig
from nautilus_trader.model import ActorId, GreeksConvention, InstrumentId, OptionGreeks
from nautilus_trader.persistence import ParquetDataCatalog

_INSTRUMENT_ID = InstrumentId.from_str("BTC-20240329-50000-C.DERIBIT")


def _make_greeks() -> OptionGreeks:
    return OptionGreeks(
        instrument_id=_INSTRUMENT_ID,
        delta=0.55,
        gamma=0.012,
        vega=3.4,
        theta=-1.2,
        rho=0.01,
        mark_iv=0.64,
        bid_iv=None,
        ask_iv=0.66,
        underlying_price=50_000.0,
        open_interest=None,
        ts_event=1,
        ts_init=2,
        convention=GreeksConvention.PRICE_ADJUSTED,
    )


class _GreeksRecorder(DataActor):
    # PyO3 #[new] maps to __new__, so subclasses must not define __init__,
    # and the `received` list is attached to the instance after construction.
    def on_option_greeks(self, greeks: OptionGreeks) -> None:
        """
        On option greeks.
        """
        self.received.append(greeks)


@pytest.fixture
def catalog(tmp_path: Path) -> ParquetDataCatalog:
    """
    Catalog.
    """
    path = str(tmp_path / "catalog")
    os.makedirs(path, exist_ok=True)
    return ParquetDataCatalog(path)


def test_write_and_query_option_greeks_round_trip(catalog: ParquetDataCatalog) -> None:
    """
    Test write and query option greeks round trip.
    """
    # Arrange
    written = _make_greeks()

    # Act
    catalog.write_option_greeks([written])
    loaded = catalog.query_option_greeks()

    # Assert
    assert len(loaded) == 1
    greeks = loaded[0]
    assert isinstance(greeks, OptionGreeks)
    assert greeks.instrument_id == _INSTRUMENT_ID
    assert greeks.delta == 0.55
    assert greeks.gamma == 0.012
    assert greeks.vega == 3.4
    assert greeks.theta == -1.2
    assert greeks.rho == 0.01
    assert greeks.mark_iv == 0.64
    assert greeks.ask_iv == 0.66
    assert greeks.bid_iv is None
    assert greeks.underlying_price == 50_000.0
    assert greeks.open_interest is None
    assert greeks.ts_event == 1
    assert greeks.ts_init == 2
    assert greeks.convention == GreeksConvention.PRICE_ADJUSTED


def test_catalog_loaded_greeks_reach_on_option_greeks(catalog: ParquetDataCatalog) -> None:
    """
    Test catalog loaded greeks reach on option greeks.
    """
    # Arrange: persist, then load back through the non-FFI catalog query path
    catalog.write_option_greeks([_make_greeks()])
    loaded = catalog.query_option_greeks()
    assert len(loaded) == 1

    recorder = _GreeksRecorder(
        DataActorConfig(
            actor_id=ActorId("GREEKS-RECORDER"),
            log_events=False,
            log_commands=False,
        ),
    )
    recorder.received = []

    # Act: a catalog-loaded greeks object is a valid `on_option_greeks` payload
    recorder.on_option_greeks(loaded[0])

    # Assert
    assert len(recorder.received) == 1
    received = recorder.received[0]
    assert received.instrument_id == _INSTRUMENT_ID
    assert received.delta == 0.55
    assert received.bid_iv is None
    assert received.convention == GreeksConvention.PRICE_ADJUSTED
