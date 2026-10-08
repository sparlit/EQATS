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


# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
# -------------------------------------------------------------------------------------------------
"""
Example of historical download.
"""


import asyncio
import datetime as dt
import os

from _common import (
    default_aapl_instrument_id,
    default_stock_contracts,
    env_bool,
    env_int,
    instrument_ids,
    instrument_provider_config,
    resolve_ib_endpoint,
)
from nautilus_trader.adapters import interactive_brokers
from nautilus_trader.persistence import ParquetDataCatalog


def historical_end() -> dt.datetime:
    """
    Historical end.
    """
    value = os.getenv("IB_V2_HISTORICAL_END")
    if value:
        return dt.datetime.fromisoformat(value).astimezone(dt.UTC)
    return dt.datetime(2026, 4, 30, 16, 30, tzinfo=dt.UTC)


async def main() -> None:
    """
    Run the example.
    """
    ib = interactive_brokers
    host, port = resolve_ib_endpoint()
    trading_hours = ib.IbTradingHours.EXTENDED
    requested_ids = [
        os.getenv("IB_V2_HISTORICAL_INSTRUMENT_ID", default_aapl_instrument_id()),
    ]
    provider_config = instrument_provider_config(load_ids=requested_ids)
    provider = ib.InteractiveBrokersInstrumentProvider(provider_config)
    client_config = ib.InteractiveBrokersDataClientConfig(
        host=host,
        port=port,
        client_id=env_int("IB_V2_HIST_CLIENT_ID", 180),
        connection_timeout=env_int("IB_V2_CONNECTION_TIMEOUT", 10),
        request_timeout=env_int("IB_V2_REQUEST_TIMEOUT", 60),
        use_regular_trading_hours=trading_hours.use_rth(),
        instrument_provider=provider_config,
    )

    if not env_bool("IB_V2_RUN_CLIENT"):
        print(
            "Built IB historical client. Set IB_V2_RUN_CLIENT=1 to request data.",
            flush=True,
        )
        return

    client = ib.HistoricalInteractiveBrokersClient(provider, client_config)
    print("Requesting instruments...", flush=True)
    instruments = await client.request_instruments(
        instrument_ids=instrument_ids(requested_ids),
        contracts=default_stock_contracts()[:1],
    )
    print(f"Loaded {len(instruments)} instrument(s)", flush=True)

    print("Requesting bars...", flush=True)
    bars = await client.request_bars(
        bar_specifications=["1-HOUR-LAST"],
        end_date_time=historical_end(),
        duration=os.getenv("IB_V2_HISTORICAL_DURATION", "1 D"),
        instrument_ids=instrument_ids(requested_ids),
        use_rth=trading_hours.use_rth(),
        timeout=env_int("IB_V2_HISTORICAL_TIMEOUT", 60),
    )
    print(f"Downloaded {len(bars)} bar(s)", flush=True)
    for bar in bars[:5]:
        print(bar, flush=True)

    print("Requesting trade ticks...", flush=True)
    ticks_end = historical_end().replace(hour=10, minute=1)
    ticks_start = ticks_end - dt.timedelta(minutes=1)
    trade_ticks = await client.request_ticks(
        tick_type=ib.IbHistoricalTickType.TRADES,
        start_date_time=ticks_start,
        end_date_time=ticks_end,
        instrument_ids=instrument_ids(requested_ids),
        use_rth=trading_hours.use_rth(),
        timeout=env_int("IB_V2_HISTORICAL_TIMEOUT", 60),
    )
    print(f"Downloaded {len(trade_ticks)} trade tick(s)", flush=True)

    print("Requesting quote ticks...", flush=True)
    quote_ticks = await client.request_ticks(
        tick_type=ib.IbHistoricalTickType.BID_ASK,
        start_date_time=ticks_start,
        end_date_time=ticks_end,
        instrument_ids=instrument_ids(requested_ids),
        use_rth=trading_hours.use_rth(),
        timeout=env_int("IB_V2_HISTORICAL_TIMEOUT", 60),
    )
    print(f"Downloaded {len(quote_ticks)} quote tick(s)", flush=True)

    catalog = ParquetDataCatalog("./catalog")
    catalog.write_instruments(instruments)
    catalog.write_bars(bars)
    catalog.write_trade_ticks(trade_ticks)
    catalog.write_quote_ticks(quote_ticks)


if __name__ == "__main__":
    asyncio.run(main())
