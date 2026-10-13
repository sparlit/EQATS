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
Parquet catalog regression tests.
"""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from nautilus_trader.common import Cache, Clock, Environment
from nautilus_trader.model import NautilusDataType
from nautilus_trader.persistence import CatalogBackend, ParquetDataCatalog, StreamingFeatherWriter
from nautilus_trader.persistence.catalog_to_df import CatalogOutput, query_catalog
from tests.stubs import TestDataProviderPyo3


def test_parquet_roundtrip_and_dataframe_preserve_nanoseconds(tmp_path) -> None:
    """
    Verify parquet roundtrip and dataframe preserve nanoseconds.
    """
    catalog = ParquetDataCatalog(str(tmp_path))
    timestamps = [1_700_000_000_000_000_001, 1_700_000_000_000_000_123]
    quotes = [TestDataProviderPyo3.quote_tick(ts_event=ts - 1, ts_init=ts) for ts in timestamps]
    catalog.write_quote_ticks(quotes)

    actual = catalog.query_quote_ticks()
    table = query_catalog(catalog, NautilusDataType.QuoteTick, output=CatalogOutput.ARROW)
    physical = pq.read_table(next(tmp_path.rglob("*.parquet")))

    assert actual == quotes
    assert table.schema.field("ts_init").type == pa.timestamp("ns", tz="UTC")
    assert table.column("ts_init").cast(pa.int64()).to_pylist() == timestamps
    assert table.column("ts_event").cast(pa.int64()).to_pylist() == [ts - 1 for ts in timestamps]
    assert physical.schema.field("ts_init").type == pa.timestamp("ns", tz="UTC")
    assert physical.column("ts_init").cast(pa.int64()).to_pylist() == timestamps


def test_parquet_rejects_snapshot_queries(tmp_path) -> None:
    """
    Verify parquet rejects snapshot queries.
    """
    catalog = ParquetDataCatalog(str(tmp_path))
    with pytest.raises(ValueError, match="as_of is not supported by ParquetDataCatalog"):
        query_catalog(catalog, NautilusDataType.QuoteTick, as_of=1)


def test_parquet_converts_current_feather_stream(tmp_path) -> None:
    """
    Verify parquet converts current feather stream.
    """
    catalog = ParquetDataCatalog(str(tmp_path))
    staging = tmp_path / "backtest" / "run"
    staging.mkdir(parents=True)
    writer = StreamingFeatherWriter(str(staging), cache=Cache(), clock=Clock.new_test())
    quote = TestDataProviderPyo3.quote_tick(ts_event=123_456_788, ts_init=123_456_789)
    writer.write(quote)
    writer.close()

    catalog.convert_stream_to_data("run", NautilusDataType.QuoteTick)

    assert catalog.query_quote_ticks() == [quote]


def test_parquet_converts_feather_stream_for_environment(tmp_path) -> None:
    """
    Verify parquet converts a feather stream from the environment's run folder.
    """
    catalog = ParquetDataCatalog(str(tmp_path))
    staging = tmp_path / "live" / "run"
    staging.mkdir(parents=True)
    writer = StreamingFeatherWriter(str(staging), cache=Cache(), clock=Clock.new_test())
    quote = TestDataProviderPyo3.quote_tick(ts_event=123_456_788, ts_init=123_456_789)
    writer.write(quote)
    writer.close()

    catalog.convert_stream_to_data("run", NautilusDataType.QuoteTick)
    backtest_quotes = catalog.query_quote_ticks()
    catalog.convert_stream_to_data("run", NautilusDataType.QuoteTick, environment=Environment.LIVE)

    assert backtest_quotes == []
    assert catalog.query_quote_ticks() == [quote]


def test_parquet_backend_is_builtin() -> None:
    """
    Verify parquet backend is builtin.
    """
    assert CatalogBackend.from_str("parquet") == CatalogBackend.Parquet
    assert CatalogBackend.Parquet.name == "Parquet"
    assert CatalogBackend.Parquet.value == "Parquet"
