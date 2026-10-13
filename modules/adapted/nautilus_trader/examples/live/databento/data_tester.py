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
Stream Databento market data with the built-in DataTester actor.

Running this example connects to Databento (credentials from the DATABENTO_API_KEY
environment variable) and starts subscriptions for the configured instrument
immediately, logging all received data. No orders are placed.

"""


import os
from pathlib import Path

from nautilus_trader.adapters.databento import DatabentoDataClientConfig, DatabentoDataClientFactory
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import ClientId, InstrumentId, TraderId
from nautilus_trader.testkit import DataTesterConfig

DATABENTO = "DATABENTO"
TRADER_ID = TraderId.from_str("TESTER-001")
INSTRUMENT_ID = InstrumentId.from_str("AAPL.EQUS")
PUBLISHERS_FILEPATH = (
    Path(__file__).resolve().parents[3] / "crates/adapters/databento/publishers.json"
)
USE_EXCHANGE_AS_VENUE = False


def main() -> None:
    """
    Run the example.
    """
    api_key = os.getenv("DATABENTO_API_KEY")
    if not api_key:
        raise SystemExit("DATABENTO_API_KEY must be set")

    node = (
        LiveNode.builder("DATABENTO-DATA-TESTER-001", TRADER_ID, Environment.LIVE)
        .add_data_client(
            None,
            DatabentoDataClientFactory(),
            DatabentoDataClientConfig(
                api_key=api_key,
                publishers_filepath=PUBLISHERS_FILEPATH,
                use_exchange_as_venue=USE_EXCHANGE_AS_VENUE,
            ),
        )
        .build()
    )
    node.add_builtin_actor(
        "DataTester",
        DataTesterConfig(
            client_id=ClientId.from_str(DATABENTO),
            instrument_ids=[INSTRUMENT_ID],
            subscribe_trades=True,
            log_data=True,
        ),
    )

    node.run()


if __name__ == "__main__":
    main()
