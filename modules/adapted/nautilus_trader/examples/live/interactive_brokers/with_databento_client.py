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
Example of IB with Databento.
"""


import os
from pathlib import Path

from _common import (
    add_strategy_from_config,
    databento_instrument_provider_config,
    env_bool,
    env_int,
    resolve_ib_endpoint,
    schedule_node_stop,
)
from nautilus_trader.adapters import interactive_brokers
from nautilus_trader.adapters.databento import DatabentoDataClientConfig, DatabentoDataClientFactory
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId


def default_publishers_filepath() -> str:
    """
    Default publishers filepath.
    """
    return str(
        Path(__file__).resolve().parents[3]
        / "crates"
        / "adapters"
        / "databento"
        / "publishers.json",
    )


def main() -> None:
    """
    Run the example.
    """
    api_key = os.getenv("DATABENTO_API_KEY")
    if not api_key:
        raise SystemExit("DATABENTO_API_KEY must be set")

    host, port = resolve_ib_endpoint()
    trader_id = TraderId.from_str("IB-V2-DATABENTO-001")
    account_id = os.getenv("TWS_ACCOUNT") if env_bool("IB_V2_ENABLE_EXECUTION") else None
    provider_config = databento_instrument_provider_config()

    builder = LiveNode.builder(
        "IB-V2-DATABENTO-001",
        trader_id,
        Environment.LIVE,
    )
    builder = builder.with_timeout_connection(env_int("IB_V2_NODE_CONNECTION_TIMEOUT", 15))
    builder = builder.with_reconciliation(reconciliation=False)
    builder = builder.add_data_client(
        "DATABENTO",
        DatabentoDataClientFactory(),
        DatabentoDataClientConfig(
            api_key=api_key,
            publishers_filepath=os.getenv(
                "DATABENTO_PUBLISHERS_FILE",
                default_publishers_filepath(),
            ),
        ),
    )

    if account_id is not None:
        ib = interactive_brokers
        builder = builder.add_exec_client(
            None,
            ib.InteractiveBrokersExecutionClientFactory(),
            ib.InteractiveBrokersExecutionClientConfig(
                host=host,
                port=port,
                client_id=env_int("IB_V2_EXEC_CLIENT_ID", 1312),
                account_id=account_id,
                connection_timeout=env_int("IB_V2_CONNECTION_TIMEOUT", 10),
                request_timeout=env_int("IB_V2_REQUEST_TIMEOUT", 30),
                fetch_all_open_orders=False,
                instrument_provider=provider_config,
            ),
        )

    node = builder.build()
    add_strategy_from_config(
        node,
        "ib_v2_order_strategies:DatabentoSubscriptionStrategy",
    )
    print(f"Built Databento data + IB execution v2 node: {node.trader_id}", flush=True)
    if env_bool("IB_V2_RUN_NODE"):
        schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 0))
        node.run()


if __name__ == "__main__":
    main()
