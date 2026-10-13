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
Run a top-of-book imbalance strategy on the Architect AX sandbox.

Running this example connects to the AX sandbox and places live sandbox orders on
imbalance triggers. The strategy has no claimed alpha and is not intended for production
trading.

"""

from decimal import Decimal

from nautilus_trader.adapters.architect_ax import (
    AX,
    AxDataClientConfig,
    AxDataClientFactory,
    AxEnvironment,
    AxExecutionClientConfig,
    AxExecutionClientFactory,
)
from nautilus_trader.common import Environment
from nautilus_trader.config import LiveExecutionEngineConfig, LiveRiskEngineConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import AccountId, InstrumentId, StrategyId, TraderId
from strategies import OrderBookImbalance, OrderBookImbalanceConfig

# WARNING: With DRY_RUN = False, this strategy submits orders to the configured
# environment. Set DRY_RUN = True to log intended trades without submitting orders.
DRY_RUN = False
TRADER_ID = TraderId.from_str("TESTER-001")
ACCOUNT_ID = AccountId.from_str("AX-001")
STRATEGY_ID = StrategyId.from_str("AX-BOOK-IMBALANCE-001")
INSTRUMENT_ID = InstrumentId.from_str(f"XAU-PERP.{AX}")
MAX_TRADE_SIZE = Decimal(1)
TRIGGER_MIN_SIZE = Decimal(1)
TRIGGER_IMBALANCE_RATIO = Decimal("0.10")
MIN_SECONDS_BETWEEN_TRIGGERS = 5.0


def main() -> None:
    """
    Run the example.
    """
    node = (
        LiveNode.builder("AX-BOOK-IMBALANCE-001", TRADER_ID, Environment.LIVE)
        .with_exec_engine_config(
            LiveExecutionEngineConfig(
                reconciliation_instrument_ids=[str(INSTRUMENT_ID)],
            ),
        )
        .with_reconciliation(reconciliation=True)
        .with_risk_engine_config(LiveRiskEngineConfig(bypass=True))
        .with_timeout_connection(20)
        .with_timeout_reconciliation(10)
        .with_timeout_portfolio(10)
        .with_timeout_disconnection_secs(10)
        .with_delay_post_stop_secs(5)
        .add_data_client(
            None,
            AxDataClientFactory(),
            AxDataClientConfig(environment=AxEnvironment.SANDBOX),
        )
        .add_exec_client(
            None,
            AxExecutionClientFactory(),
            AxExecutionClientConfig(
                account_id=ACCOUNT_ID,
                environment=AxEnvironment.SANDBOX,
            ),
        )
        .build()
    )
    node.add_strategy(
        OrderBookImbalance(
            OrderBookImbalanceConfig(
                instrument_id=INSTRUMENT_ID,
                max_trade_size=MAX_TRADE_SIZE,
                trigger_min_size=TRIGGER_MIN_SIZE,
                trigger_imbalance_ratio=TRIGGER_IMBALANCE_RATIO,
                min_seconds_between_triggers=MIN_SECONDS_BETWEEN_TRIGGERS,
                dry_run=DRY_RUN,
                strategy_id=STRATEGY_ID,
            ),
        ),
    )

    node.run()


if __name__ == "__main__":
    main()
