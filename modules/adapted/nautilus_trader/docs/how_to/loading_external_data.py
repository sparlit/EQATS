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


# %% [markdown]
# # Loading External Data
#
# Load CSV market data into the Parquet data catalog, then run a backtest with
# `BacktestNode`. This is a common workflow when you have historical data from an
# external vendor that is not directly supported by a NautilusTrader adapter.
#
# [View source on GitHub](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/how_to/loading_external_data.py).

# %% [markdown]
# ## Prerequisites
#
# - Python 3.13+
# - [NautilusTrader](https://pypi.org/project/nautilus_trader/) 2.x installed
#   (`pip install -U --pre nautilus_trader`)
# - pandas (`pip install pandas`), needed only for the histdata path below

# %%
import os
import shutil
from decimal import Decimal
from pathlib import Path

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.common import LogLevel
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    LoggerConfig,
)
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, Currency, NautilusDataType, OmsType, Quantity
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import EmaCrossConfig

# %% [markdown]
# ## Load and wrangle the data
#
# Place CSV tick files (e.g. from [histdata.com](https://www.histdata.com/))
# into `~/Downloads/Data/HISTDATA/`. Set the `NAUTILUS_DATA_DIR` environment
# variable to the parent directory if your data lives elsewhere.
# `TestDataProvider.quotes_from_histdata_csv` converts the rows into Nautilus
# `QuoteTick` objects. It expects the histdata ASCII tick format extracted from
# the downloaded ZIP (`.csv` or `.csv.gz`). The how-to loads only the first
# file in sorted order and labels it EUR/USD, so use a EUR/USD file or change
# the instrument.
#
# Without a download, the how-to falls back to 20,000 sample AUD/USD quote
# ticks so it still runs end to end.

# %%
DATA_DIR = Path(os.environ.get("NAUTILUS_DATA_DIR", "~/Downloads/Data")).expanduser() / "HISTDATA"

raw_files = (
    sorted(
        f
        for f in DATA_DIR.iterdir()
        if f.is_file() and (f.suffix == ".csv" or f.name.endswith(".csv.gz"))
    )
    if DATA_DIR.is_dir()
    else []
)
raw_files

# %%
if raw_files:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    ticks = TestDataProvider.quotes_from_histdata_csv(instrument, raw_files[0])
else:
    instrument = TestInstrumentProvider.default_fx_ccy("AUD/USD")
    ticks = TestDataProvider.quotes_from_truefx_csv(
        instrument,
        "truefx/audusd-ticks.csv",
        max_rows=20_000,
    )

# Vendor exports are not always monotonic; the catalog requires ascending timestamps
ticks.sort(key=lambda tick: tick.ts_init)

# %% [markdown]
# ## Write to the data catalog
#
# Create a `ParquetDataCatalog` and write the instrument definition and tick
# data. The catalog stores data in Parquet format for efficient querying across
# backtest runs. The how-to writes the catalog to `catalog/` under the working
# directory and replaces that directory on each run.

# %%
CATALOG_PATH = Path.cwd() / "catalog"

# Clear if it already exists, then create fresh
if CATALOG_PATH.exists():
    shutil.rmtree(CATALOG_PATH)
CATALOG_PATH.mkdir(parents=True)

catalog = ParquetDataCatalog(str(CATALOG_PATH))

# %%
catalog.write_instruments([instrument])
catalog.write_quote_ticks(ticks)

# %%
# Verify instruments written to catalog
catalog.instruments()

# %%
start = ticks[0].ts_event
end = ticks[-1].ts_event + 1

ticks = catalog.query_quote_ticks(identifiers=[instrument.id.value], start=start, end=end)
ticks[:10]

# %% [markdown]
# ## Configure and run the backtest
#
# Set up venue and data configs, build the node, then register the built-in
# `EmaCross` strategy. The same node and strategy pattern carries forward to
# live trading with `LiveNode`.

# %%
instrument = catalog.instruments()[0]

venue_configs = [
    BacktestVenueConfig(
        name="SIM",
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=Currency.from_str("USD"),
        starting_balances=["1000000 USD"],
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal("0.00002"),
            taker_rate=Decimal("0.00002"),
        ),
    ),
]

data_configs = [
    BacktestDataConfig(
        catalog_path=str(CATALOG_PATH),
        data_type=NautilusDataType.QuoteTick,
        instrument_id=instrument.id,
        start_time=start,
        end_time=end,
    ),
]

config = BacktestRunConfig(
    engine=BacktestEngineConfig(
        logging=LoggerConfig(stdout_level=LogLevel.ERROR),
    ),
    data=data_configs,
    venues=venue_configs,
)

# %%
node = BacktestNode(configs=[config])
node.build()
node.add_builtin_strategy(
    config.id,
    "EmaCross",
    EmaCrossConfig(
        instrument_id=instrument.id,
        trade_size=Quantity.from_int(1_000_000),
        fast_period=10,
        slow_period=20,
    ),
)

[result] = node.run()

# %%
result
