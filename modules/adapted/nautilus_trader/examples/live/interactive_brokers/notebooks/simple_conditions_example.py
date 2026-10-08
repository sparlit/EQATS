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
Interactive Brokers order conditions.
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
# # Interactive Brokers order conditions
#
# This example shows the IB tag payload for time and price conditions before it configures the
# clients. It builds offline by default. Set `IB_V2_ENABLE_ORDER_SUBMISSION=1` and
# `IB_V2_RUN_NODE=1` only for a paper-account run.

# %%

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import (
    build_ib_live_node,
    default_es_future_instrument_id,
    env_bool,
    env_int,
    ib_order_tags,
    instrument_provider_config,
    resolve_ib_endpoint,
    schedule_node_stop,
)
from ib_v2_order_strategies import (
    IbV2OrderStrategy,
    contract_id_from_instrument,
    env_ib_trigger_method,
    env_price,
    env_quantity,
)
from nautilus_trader.adapters import interactive_brokers as ib
from nautilus_trader.model import OrderSide, TimeInForce

# %%
INSTRUMENT_ID = os.getenv(
    "IB_V2_ORDER_INSTRUMENT_ID",
    default_es_future_instrument_id(),
)


# %% [markdown]
# The first order activates after a UTC timestamp. The optional second order uses the qualified IB
# contract ID and activates when the configured trigger price is reached.


# %%
class ConditionsExample(IbV2OrderStrategy):
    """
    Conditions example.
    """

    strategy_id_value = "IB-V2-CONDITIONS-STRATEGY"
    instrument_id_value = INSTRUMENT_ID

    def submit_example_orders(self) -> None:
        """
        Submit example orders.
        """
        time_condition = {
            "type": ib.IbConditionKind.TIME.as_str(),
            "time": (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)).strftime(
                "%Y%m%d-%H:%M:%S",
            ),
            "isMore": True,
            "conjunction": ib.IbConditionConjunction.AND.as_str(),
        }
        time_order = self.limit_order(
            self.client_order_id("TIME-CONDITION"),
            OrderSide.SELL,
            env_quantity("IB_V2_CONDITION_QUANTITY"),
            env_price("IB_V2_CONDITION_TIME_LIMIT_PRICE", "6100.00"),
            TimeInForce.GTC,
            tags=[
                ib_order_tags(
                    conditions=[time_condition],
                    conditionsCancelOrder=env_bool(
                        "IB_V2_CONDITIONS_CANCEL_ORDER",
                        False,
                    ),
                ),
            ],
        )
        self.submit_ib_order(time_order)

        if not env_bool("IB_V2_ENABLE_PRICE_CONDITION", True):
            return

        contract_id = env_int("IB_V2_CONDITION_CONTRACT_ID", 0) or (
            contract_id_from_instrument(self.instrument)
        )

        if contract_id <= 0:
            print("Skipping the price condition because the IB contract ID is missing.")
            return

        price_condition = {
            "type": ib.IbConditionKind.PRICE.as_str(),
            "conId": contract_id,
            "exchange": os.getenv("IB_V2_CONDITION_EXCHANGE", "CME"),
            "isMore": True,
            "price": float(os.getenv("IB_V2_CONDITION_TRIGGER_PRICE", "6000.0")),
            "triggerMethod": env_ib_trigger_method(
                "IB_V2_CONDITION_TRIGGER_METHOD",
                ib.IbTriggerMethod.DEFAULT,
            ),
            "conjunction": ib.IbConditionConjunction.AND.as_str(),
        }
        price_order = self.limit_order(
            self.client_order_id("PRICE-CONDITION"),
            OrderSide.BUY,
            env_quantity("IB_V2_CONDITION_QUANTITY"),
            env_price("IB_V2_CONDITION_PRICE_LIMIT_PRICE", "5950.00"),
            TimeInForce.GTC,
            tags=[
                ib_order_tags(
                    conditions=[price_condition],
                    conditionsCancelOrder=env_bool(
                        "IB_V2_CONDITIONS_CANCEL_ORDER",
                        False,
                    ),
                ),
            ],
        )
        self.submit_ib_order(price_order)


# %%
def main() -> None:
    """
    Run the example.
    """
    host, port = resolve_ib_endpoint()
    account_id = os.getenv("TWS_ACCOUNT") if env_bool("IB_V2_ENABLE_ORDER_SUBMISSION") else None
    if env_bool("IB_V2_ENABLE_ORDER_SUBMISSION") and account_id is None:
        raise RuntimeError("Set TWS_ACCOUNT before enabling conditional order submission")

    provider_config = instrument_provider_config(load_ids=[INSTRUMENT_ID])
    node = build_ib_live_node(
        name="IB-V2-CONDITIONS-001",
        trader_id="IB-V2-CONDITIONS-001",
        host=host,
        port=port,
        data_client_id=env_int("IB_V2_DATA_CLIENT_ID", 1421),
        exec_client_id=env_int("IB_V2_EXEC_CLIENT_ID", 1422),
        account_id=account_id,
        provider_config=provider_config,
    )
    node.add_strategy(ConditionsExample())

    print(f"Built conditional-order node for {INSTRUMENT_ID}.", flush=True)
    if env_bool("IB_V2_RUN_NODE"):
        schedule_node_stop(node, env_int("IB_V2_AUTO_STOP_SECONDS", 20))
        node.run()


# %%
if __name__ == "__main__":
    main()
