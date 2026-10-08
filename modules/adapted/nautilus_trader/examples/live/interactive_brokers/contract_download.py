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
Example of contract download.
"""


import asyncio

from _common import (
    default_stock_contracts,
    env_bool,
    env_int,
    instrument_provider_config,
    resolve_ib_endpoint,
)
from nautilus_trader.adapters import interactive_brokers


async def main() -> None:
    """
    Run the example.
    """
    ib = interactive_brokers
    host, port = resolve_ib_endpoint()
    provider_config = instrument_provider_config()
    provider = ib.InteractiveBrokersInstrumentProvider(provider_config)
    client_config = ib.InteractiveBrokersDataClientConfig(
        host=host,
        port=port,
        client_id=env_int("IB_V2_CONTRACT_CLIENT_ID", 181),
        connection_timeout=env_int("IB_V2_CONNECTION_TIMEOUT", 10),
        request_timeout=env_int("IB_V2_REQUEST_TIMEOUT", 30),
        instrument_provider=provider_config,
    )

    if not env_bool("IB_V2_RUN_CLIENT"):
        print(
            "Built IB contract client. Set IB_V2_RUN_CLIENT=1 to request contracts.",
            flush=True,
        )
        return

    client = ib.HistoricalInteractiveBrokersClient(provider, client_config)
    print("Requesting contracts...", flush=True)
    instruments = await client.request_instruments(contracts=default_stock_contracts())
    print(f"Loaded {len(instruments)} instrument(s)", flush=True)
    for instrument in instruments:
        print(instrument.id, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
