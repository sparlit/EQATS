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


#!/usr/bin/env python3
# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Test Derive execution with the built-in ExecTester strategy.

This example connects to the Derive testnet and places live testnet orders. On start it
opens a position with an IOC order, then maintains post-only limit quotes on both sides
of the book. On stop it cancels all orders and closes all positions. The strategy has no
alpha advantage whatsoever and is not intended for production trading.

"""


from decimal import Decimal

from nautilus_trader.adapters.derive import (
    DERIVE,
    DeriveDataClientConfig,
    DeriveDataClientFactory,
    DeriveEnvironment,
    DeriveExecutionClientConfig,
    DeriveExecutionClientFactory,
)
from nautilus_trader.common import Environment
from nautilus_trader.config import LiveRiskEngineConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import (
    AccountId,
    ClientId,
    InstrumentId,
    Quantity,
    StrategyId,
    TimeInForce,
    TraderId,
)
from nautilus_trader.testkit import ExecTesterConfig

# WARNING: With DRY_RUN = False, this tester submits orders to the configured
# environment and may use real funds. Set DRY_RUN = True to connect without
# submitting orders or sending shutdown cancel/close commands.
DRY_RUN = False
DERIVE_ENVIRONMENT = DeriveEnvironment.TESTNET
TRADER_ID = TraderId.from_str("TESTER-001")
ACCOUNT_ID = AccountId.from_str("DERIVE-001")
STRATEGY_ID = StrategyId.from_str("EXEC_TESTER-001")
INSTRUMENT_ID = InstrumentId.from_str(f"ETH-PERP.{DERIVE}")
CURRENCY = "ETH"
ORDER_QTY = "0.1"
MAX_FEE_PER_CONTRACT = "1000"


def main() -> None:
    """
    Run the example.
    """
    exec_config = DeriveExecutionClientConfig(
        account_id=ACCOUNT_ID,
        environment=DERIVE_ENVIRONMENT,
        max_fee_per_contract=Decimal(MAX_FEE_PER_CONTRACT),
    )

    node = (
        LiveNode.builder("DERIVE-EXEC-TESTER-001", TRADER_ID, Environment.LIVE)
        .with_reconciliation(reconciliation=True)
        .with_risk_engine_config(LiveRiskEngineConfig(bypass=True))
        .add_data_client(
            None,
            DeriveDataClientFactory(),
            DeriveDataClientConfig(
                environment=DERIVE_ENVIRONMENT,
                currencies=[CURRENCY],
            ),
        )
        .add_exec_client(
            None,
            DeriveExecutionClientFactory(),
            exec_config,
        )
        .build()
    )
    node.add_builtin_strategy(
        "ExecTester",
        ExecTesterConfig(
            strategy_id=STRATEGY_ID,
            instrument_id=INSTRUMENT_ID,
            client_id=ClientId.from_str(DERIVE),
            external_order_instrument_ids=[INSTRUMENT_ID],
            order_qty=Quantity.from_str(ORDER_QTY),
            subscribe_quotes=True,
            subscribe_trades=True,
            open_position_on_start_qty=Decimal(ORDER_QTY),
            open_position_on_first_quote=True,
            open_position_time_in_force=TimeInForce.IOC,
            enable_limit_buys=True,
            enable_limit_sells=True,
            use_post_only=True,
            cancel_orders_on_stop=True,
            close_positions_on_stop=True,
            dry_run=DRY_RUN,
            log_data=False,
        ),
    )

    node.run()


if __name__ == "__main__":
    main()
