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
Example of option greeks.
"""


import asyncio
import os

from _common import (
    add_strategy_from_config,
    build_ib_live_node,
    default_es_future_instrument_id,
    default_es_put_option_instrument_id,
    env_bool,
    env_int,
    instrument_provider_config,
    is_ib_endpoint_reachable,
    resolve_ib_endpoint,
    schedule_node_stop,
)
from nautilus_trader.adapters import interactive_brokers
from nautilus_trader.model import InstrumentId


async def main() -> None:
    """
    Run the example.
    """
    ib = interactive_brokers
    host, port = resolve_ib_endpoint()
    provider_config = instrument_provider_config(
        load_ids=[
            os.getenv(
                "IB_V2_OPTION_UNDERLYING_INSTRUMENT_ID",
                default_es_future_instrument_id(),
            ),
            os.getenv("IB_V2_OPTION_INSTRUMENT_ID", default_es_put_option_instrument_id()),
        ],
    )
    provider = ib.InteractiveBrokersInstrumentProvider(provider_config)
    client_config = ib.InteractiveBrokersDataClientConfig(
        host=host,
        port=port,
        client_id=env_int("IB_V2_OPTION_CLIENT_ID", 1401),
        connection_timeout=env_int("IB_V2_CONNECTION_TIMEOUT", 10),
        request_timeout=env_int("IB_V2_REQUEST_TIMEOUT", 30),
        market_data_type=ib.MarketDataType.DELAYED,
        instrument_provider=provider_config,
    )

    if not env_bool("IB_V2_RUN_CLIENT"):
        print(
            "Built IB option greeks client. Set IB_V2_RUN_CLIENT=1 to request data.",
            flush=True,
        )
        return

    if not is_ib_endpoint_reachable(host, port):
        print(f"IB Gateway/TWS is not reachable at {host}:{port}", flush=True)
        return

    try:
        client = ib.HistoricalInteractiveBrokersClient(provider, client_config)
    except RuntimeError as e:
        print(f"Failed to connect to IB Gateway/TWS at {host}:{port}: {e}", flush=True)
        return

    print("Requesting option instruments...", flush=True)
    instruments = await client.request_instruments(
        instrument_ids=[
            InstrumentId.from_str(
                os.getenv("IB_V2_OPTION_INSTRUMENT_ID", default_es_put_option_instrument_id()),
            ),
        ],
    )
    print(f"Loaded {len(instruments)} option instrument(s)", flush=True)
    for instrument in instruments:
        print(instrument.id, flush=True)

    if instruments:
        os.environ.setdefault("IB_V2_OPTION_INSTRUMENT_ID", str(instruments[0].id))

    if not env_bool("IB_V2_RUN_NODE"):
        print(
            "Set IB_V2_RUN_NODE=1 to subscribe to option greeks through a v2 strategy.",
            flush=True,
        )
        return

    node = build_ib_live_node(
        name="IB-V2-OPTION-GREEKS-001",
        trader_id="IB-V2-OPTION-GREEKS-001",
        host=host,
        port=port,
        data_client_id=env_int("IB_V2_OPTION_NODE_CLIENT_ID", 1402),
        provider_config=provider_config,
    )
    add_strategy_from_config(
        node,
        "ib_v2_order_strategies:OptionGreeksStrategy",
    )
    schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 30))
    node.run()


if __name__ == "__main__":
    asyncio.run(main())
