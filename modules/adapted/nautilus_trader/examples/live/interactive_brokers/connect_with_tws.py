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
Example of connect with tws.
"""


import os

from _common import (
    add_strategy_from_config,
    build_ib_live_node,
    default_spx_index_instrument_id,
    env_bool,
    env_int,
    instrument_provider_config,
    resolve_ib_endpoint,
    schedule_node_stop,
)


def main() -> None:
    """
    Run the example.
    """
    host, port = resolve_ib_endpoint()
    account_id = os.getenv("TWS_ACCOUNT") if env_bool("IB_V2_ENABLE_EXECUTION") else None
    os.environ.setdefault("IB_V2_SUBSCRIBE_INDEX_PRICES", "1")
    subscription_id = os.getenv(
        "IB_V2_SUBSCRIPTION_INSTRUMENT_ID",
        default_spx_index_instrument_id(),
    )
    provider_config = instrument_provider_config(
        load_ids=[
            subscription_id,
        ],
    )

    node = build_ib_live_node(
        name="IB-V2-TWS-001",
        trader_id="IB-V2-TWS-001",
        host=host,
        port=port,
        data_client_id=env_int("IB_V2_DATA_CLIENT_ID", 1301),
        exec_client_id=env_int("IB_V2_EXEC_CLIENT_ID", 1302),
        account_id=account_id,
        provider_config=provider_config,
    )
    add_strategy_from_config(
        node,
        "ib_v2_order_strategies:IbV2SubscriptionStrategy",
    )

    if env_bool("IB_V2_RUN_NODE"):
        print(
            f"Running v2 IB node against {host}:{port}; press Ctrl+C to stop.",
            flush=True,
        )
        schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 0))
        node.run()
    else:
        print("Built v2 IB TWS node. Set IB_V2_RUN_NODE=1 to connect.", flush=True)


if __name__ == "__main__":
    main()
