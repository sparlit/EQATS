from __future__ import annotations

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
"""
Regression tests for postponed custom-data annotations.
"""


import pyarrow as pa
import pytest
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.custom import customdataclass


@customdataclass
class AnnotatedData:
    """
    Custom data with postponed field annotations.
    """

    count: int
    instrument_id: InstrumentId
    values: dict[str, int]


@pytest.mark.parametrize("representation", ["json", "arrow"])
def test_postponed_custom_data_annotations_roundtrip(representation: str) -> None:
    """
    Preserve declared fields through JSON and Arrow round trips.
    """
    original = AnnotatedData(
        ts_event=17,
        ts_init=29,
        count=43,
        instrument_id=InstrumentId.from_str("EUR/USD.SIM"),
        values={"bid": 61, "ask": 73},
    )
    schema = AnnotatedData.arrow_schema_py()

    if representation == "json":
        restored = AnnotatedData.from_json(original.to_json())
    else:
        batch = original.encode_record_batch_py([original])
        [restored] = AnnotatedData.decode_record_batch_py({}, batch)

    assert schema == pa.schema(
        [
            pa.field("count", pa.int64()),
            pa.field("instrument_id", pa.string()),
            pa.field("values", pa.string()),
            pa.field("type", pa.string(), nullable=False),
            pa.field("ts_event", pa.timestamp("ns", tz="UTC"), nullable=False),
            pa.field("ts_init", pa.timestamp("ns", tz="UTC"), nullable=False),
        ],
    )
    assert restored == original
    assert restored.ts_event == 17
    assert restored.ts_init == 29
    assert type(restored.instrument_id) is InstrumentId
    assert type(restored.values) is dict


@customdataclass
class InheritedData:
    """
    Base fields included in a derived custom-data schema.
    """

    count: int = 7


@customdataclass
class DerivedData(InheritedData):
    """
    Custom data extending a base dataclass.
    """

    value: int = 11


def test_inherited_custom_data_fields_roundtrip() -> None:
    """
    Preserve non-default inherited values through Arrow.
    """
    original = DerivedData(ts_event=17, ts_init=29, count=43, value=61)
    batch = original.encode_record_batch_py([original])
    [restored] = DerivedData.decode_record_batch_py({}, batch)

    assert batch.schema.names == ["count", "value", "type", "ts_event", "ts_init"]
    assert restored == original
    assert restored.ts_event == 17
    assert restored.ts_init == 29
