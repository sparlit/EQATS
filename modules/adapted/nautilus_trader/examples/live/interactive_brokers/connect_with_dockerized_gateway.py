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
Example of connect with dockerized gateway.
"""


import os

from _common import (
    add_strategy_from_config,
    build_ib_live_node,
    default_docker_subscription_instrument_id,
    docker_instrument_provider_config,
    env_bool,
    env_int,
    is_ib_endpoint_reachable,
    resolve_ib_endpoint,
    schedule_node_stop,
)
from nautilus_trader.adapters import interactive_brokers


def main() -> None:
    """
    Run the example.
    """
    ib = interactive_brokers
    host, port = resolve_ib_endpoint()
    gateway = None
    run_node = env_bool("IB_V2_RUN_NODE")

    if run_node and (
        not is_ib_endpoint_reachable(host, port) or env_bool("IB_V2_FORCE_DOCKERIZED_GATEWAY")
    ):
        username = os.getenv("TWS_USERNAME")
        password = os.getenv("TWS_PASSWORD")
        if not username or not password:
            raise RuntimeError(
                "TWS_USERNAME and TWS_PASSWORD are required to start Dockerized IB Gateway",
            )

        config = ib.DockerizedIBGatewayConfig(
            username=username,
            password=password,
            read_only_api=not env_bool("IB_V2_ENABLE_EXECUTION"),
            timeout=env_int("IB_V2_DOCKER_TIMEOUT", 300),
        )
        gateway = ib.DockerizedIBGateway(config)
        gateway.safe_start_blocking(config.timeout)
        host = gateway.host
        port = gateway.port

    account_id = os.getenv("TWS_ACCOUNT") if env_bool("IB_V2_ENABLE_EXECUTION") else None
    os.environ.setdefault(
        "IB_V2_SUBSCRIPTION_INSTRUMENT_ID",
        default_docker_subscription_instrument_id(),
    )
    os.environ.setdefault("IB_V2_SUBSCRIBE_QUOTES", "1")
    provider_config = docker_instrument_provider_config()
    node = build_ib_live_node(
        name="IB-V2-DOCKER-001",
        trader_id="IB-V2-DOCKER-001",
        host=host,
        port=port,
        data_client_id=env_int("IB_V2_DATA_CLIENT_ID", 101),
        exec_client_id=env_int("IB_V2_EXEC_CLIENT_ID", 102),
        account_id=account_id,
        provider_config=provider_config,
    )
    add_strategy_from_config(
        node,
        "ib_v2_order_strategies:IbV2SubscriptionStrategy",
    )

    if run_node:
        print(
            f"Running v2 IB node against {host}:{port}; press Ctrl+C to stop.",
            flush=True,
        )
        schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 0))
        try:
            node.run()
        finally:
            if gateway is not None:
                gateway.stop_blocking()
    else:
        print(
            "Built v2 Dockerized IB Gateway node. Set IB_V2_RUN_NODE=1 to connect.",
            flush=True,
        )


if __name__ == "__main__":
    main()
