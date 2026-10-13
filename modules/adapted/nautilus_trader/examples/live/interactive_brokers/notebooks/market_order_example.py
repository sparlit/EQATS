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


"""
Interactive Brokers market order.
"""

# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Interactive Brokers market order
#
# This example selects a current ES futures contract, creates one market order, and configures the
# IB clients. It builds offline by default. Set `IB_V2_ENABLE_ORDER_SUBMISSION=1` and
# `IB_V2_RUN_NODE=1` only for a paper-account run.

# %%

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import (
    build_ib_live_node,
    default_es_future_instrument_id,
    env_bool,
    env_int,
    instrument_provider_config,
    resolve_ib_endpoint,
    schedule_node_stop,
)
from ib_v2_order_strategies import IbV2OrderStrategy, env_order_side, env_quantity
from nautilus_trader.model import OrderSide

# %%
INSTRUMENT_ID = os.getenv(
    "IB_V2_ORDER_INSTRUMENT_ID",
    default_es_future_instrument_id(),
)


# %% [markdown]
# The strategy waits until the selected instrument is available, then submits exactly one market
# order. Set `IB_V2_MARKET_SIDE=SELL` to reverse the default side.


# %%
class MarketOrderExample(IbV2OrderStrategy):
    """
    Market order example.
    """

    strategy_id_value = "IB-V2-MARKET-STRATEGY"
    instrument_id_value = INSTRUMENT_ID

    def submit_example_orders(self) -> None:
        """
        Submit example orders.
        """
        order = self.market_order(
            self.client_order_id("MARKET"),
            env_order_side("IB_V2_MARKET_SIDE", OrderSide.BUY),
            env_quantity("IB_V2_MARKET_QUANTITY"),
        )
        self.submit_ib_order(order)


# %%
def main() -> None:
    """
    Run the example.
    """
    host, port = resolve_ib_endpoint()
    account_id = os.getenv("TWS_ACCOUNT") if env_bool("IB_V2_ENABLE_ORDER_SUBMISSION") else None
    if env_bool("IB_V2_ENABLE_ORDER_SUBMISSION") and account_id is None:
        raise RuntimeError("Set TWS_ACCOUNT before enabling market order submission")

    provider_config = instrument_provider_config(load_ids=[INSTRUMENT_ID])
    node = build_ib_live_node(
        name="IB-V2-MARKET-001",
        trader_id="IB-V2-MARKET-001",
        host=host,
        port=port,
        data_client_id=env_int("IB_V2_DATA_CLIENT_ID", 1511),
        exec_client_id=env_int("IB_V2_EXEC_CLIENT_ID", 1512),
        account_id=account_id,
        provider_config=provider_config,
    )
    node.add_strategy(MarketOrderExample())

    print(f"Built market-order node for {INSTRUMENT_ID}.", flush=True)
    if env_bool("IB_V2_RUN_NODE"):
        schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 20))
        node.run()


# %%
if __name__ == "__main__":
    main()
