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
Stream Betfair market data with the built-in DataTester actor.

Running the script connects to Betfair and starts subscriptions for the configured
market immediately, logging all received data. Set `BETFAIR_MARKET_ID` to an active
market and `BETFAIR_INSTRUMENT_ID` to one of its runners. No orders are placed.

"""


import os

from nautilus_trader.adapters.betfair import BetfairDataClientConfig, BetfairDataClientFactory
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import ClientId, InstrumentId, TraderId
from nautilus_trader.testkit import DataTesterConfig

BETFAIR = "BETFAIR"
TRADER_ID = TraderId.from_str("TESTER-001")
ACCOUNT_CURRENCY = "GBP"
STREAM_CONFLATE_MS = 0


def main() -> None:
    """
    Run the example.
    """
    market_id, instrument_id = load_market_target()
    builder = LiveNode.builder(
        "BETFAIR-DATA-TESTER-001",
        TRADER_ID,
        Environment.LIVE,
    ).add_data_client(
        None,
        BetfairDataClientFactory(),
        BetfairDataClientConfig(
            account_currency=ACCOUNT_CURRENCY,
            market_ids=[market_id],
            stream_conflate_ms=STREAM_CONFLATE_MS,
        ),
    )

    node = builder.build()
    node.add_builtin_actor(
        "DataTester",
        DataTesterConfig(
            client_id=ClientId.from_str(BETFAIR),
            instrument_ids=[instrument_id],
            subscribe_book_deltas=True,
            subscribe_trades=True,
            subscribe_instrument_status=True,
            can_unsubscribe=False,
            manage_book=True,
            log_data=True,
        ),
    )

    node.run()


def load_market_target() -> tuple[str, InstrumentId]:
    """
    Load market target.
    """
    market_id = os.getenv("BETFAIR_MARKET_ID")
    instrument_id = os.getenv("BETFAIR_INSTRUMENT_ID")

    if not market_id:
        raise SystemExit("BETFAIR_MARKET_ID must be set to an active Betfair market")
    if not instrument_id:
        raise SystemExit("BETFAIR_INSTRUMENT_ID must be set to a runner in BETFAIR_MARKET_ID")
    if not instrument_id.startswith(f"{market_id}-") or not instrument_id.endswith(f".{BETFAIR}"):
        raise SystemExit("BETFAIR_INSTRUMENT_ID must belong to BETFAIR_MARKET_ID")

    return market_id, InstrumentId.from_str(instrument_id)


if __name__ == "__main__":
    main()
