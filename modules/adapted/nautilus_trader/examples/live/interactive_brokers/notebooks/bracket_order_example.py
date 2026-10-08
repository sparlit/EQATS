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
Interactive Brokers bracket order.
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
# # Interactive Brokers bracket order
#
# This example selects a current ES futures contract, builds the three linked orders, and then
# configures the IB data and execution clients. It builds offline by default. Set
# `IB_V2_ENABLE_ORDER_SUBMISSION=1` and `IB_V2_RUN_NODE=1` only for a paper-account run.

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
from ib_v2_order_strategies import IbV2OrderStrategy, env_price, env_quantity
from nautilus_trader.model import ContingencyType, OrderListId, OrderSide

# %% [markdown]
# The default selector chooses a quarterly ES contract with enough time left before expiry. Override
# it with `IB_V2_ORDER_INSTRUMENT_ID` when testing a specific contract.

# %%
INSTRUMENT_ID = os.getenv(
    "IB_V2_ORDER_INSTRUMENT_ID",
    default_es_future_instrument_id(),
)


# %% [markdown]
# The entry, target, and stop share one order-list ID. Both exits depend on the entry through the
# `OTO` contingency and identify the entry as their parent.


# %%
class BracketOrderExample(IbV2OrderStrategy):
    """
    Bracket order example.
    """

    strategy_id_value = "IB-V2-BRACKET-STRATEGY"
    instrument_id_value = INSTRUMENT_ID

    def submit_example_orders(self) -> None:
        """
        Submit example orders.
        """
        quantity = env_quantity("IB_V2_BRACKET_QUANTITY")
        entry_id = self.client_order_id("ENTRY")
        target_id = self.client_order_id("TARGET")
        stop_id = self.client_order_id("STOP")
        order_list_id = OrderListId.from_str(f"{self.strategy_id}-BRACKET")
        linked_ids = [entry_id, target_id, stop_id]

        entry = self.market_order(
            entry_id,
            OrderSide.BUY,
            quantity,
            order_list_id=order_list_id,
            linked_order_ids=linked_ids,
        )
        target = self.limit_order(
            target_id,
            OrderSide.SELL,
            quantity,
            env_price("IB_V2_BRACKET_TARGET_PRICE", "6025.00"),
            contingency_type=ContingencyType.OTO,
            order_list_id=order_list_id,
            linked_order_ids=linked_ids,
            parent_order_id=entry_id,
        )
        stop = self.stop_market_order(
            stop_id,
            OrderSide.SELL,
            quantity,
            env_price("IB_V2_BRACKET_STOP_PRICE", "5975.00"),
            contingency_type=ContingencyType.OTO,
            order_list_id=order_list_id,
            linked_order_ids=linked_ids,
            parent_order_id=entry_id,
        )

        self.submit_ib_order(entry)
        self.submit_ib_order(target)
        self.submit_ib_order(stop)


# %% [markdown]
# Both clients use the same provider config so the contract resolves to the same Nautilus ID. The
# execution client is included only when order submission is enabled and `TWS_ACCOUNT` is set.


# %%
def main() -> None:
    """
    Run the example.
    """
    host, port = resolve_ib_endpoint()
    account_id = os.getenv("TWS_ACCOUNT") if env_bool("IB_V2_ENABLE_ORDER_SUBMISSION") else None
    if env_bool("IB_V2_ENABLE_ORDER_SUBMISSION") and account_id is None:
        raise RuntimeError("Set TWS_ACCOUNT before enabling bracket order submission")

    provider_config = instrument_provider_config(load_ids=[INSTRUMENT_ID])
    node = build_ib_live_node(
        name="IB-V2-BRACKET-001",
        trader_id="IB-V2-BRACKET-001",
        host=host,
        port=port,
        data_client_id=env_int("IB_V2_DATA_CLIENT_ID", 1401),
        exec_client_id=env_int("IB_V2_EXEC_CLIENT_ID", 1402),
        account_id=account_id,
        provider_config=provider_config,
    )
    node.add_strategy(BracketOrderExample())

    print(f"Built bracket-order node for {INSTRUMENT_ID}.", flush=True)
    if env_bool("IB_V2_RUN_NODE"):
        schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 20))
        node.run()


# %%
if __name__ == "__main__":
    main()
