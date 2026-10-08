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
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Example of a minimal strategy.
"""

import datetime as dt

from nautilus_trader.common import LogColor
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model import Bar, BarType, OrderSide, Quantity, TimeInForce
from nautilus_trader.trading import Strategy


class DemoStrategy(Strategy):
    """
    Collect demo strategy tests.
    """

    def __new__(cls, *_args: object, **_kwargs: object) -> object:
        """
        Create a new instance.
        """
        return super().__new__(cls)

    def __init__(self, input_bartype: BarType) -> None:
        """
        Initialize the instance.
        """
        super().__init__()

        # Input data
        self.input_bartype = input_bartype
        self.instrument_id = input_bartype.instrument_id
        self.bars_processed = 0

        # Order placed
        self.order_placed = False

        # Start/End time of strategy
        self.start_time = None
        self.end_time = None

    def on_start(self) -> None:
        """
        On start.
        """
        # Remember and log start time of strategy
        self.start_time = dt.datetime.now(dt.UTC)
        log_msg = f"Strategy started at: {self.start_time}"
        self.log.info(log_msg)

        # Subscribe to primary data
        self.subscribe_bars(self.input_bartype)

    def on_bar(self, bar: Bar) -> None:
        """
        On bar.
        """
        self.bars_processed += 1
        log_msg = f"Bar #{self.bars_processed} | Time: {unix_nanos_to_dt(bar.ts_event):%Y-%m-%d %H:%M:%S} | Bar: {bar}"
        self.log.info(
            log_msg,
            color=LogColor.BLUE,
        )

        # Enter: SELL MARKET order (at 3rd bar)
        if not self.order_placed and self.bars_processed == 3:
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1_000),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self.order_placed = True
            log_msg = f"Market order placed at {bar.close}"
            self.log.info(log_msg, color=LogColor.GREEN)

        # Exit: BUY MARKET order (at 6th bar)
        if self.order_placed and self.bars_processed == 6:
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(1_000),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self.order_placed = True
            log_msg = f"Market order placed at {bar.close}"
            self.log.info(log_msg, color=LogColor.RED)

    def on_stop(self) -> None:
        """
        On stop.
        """
        # Remember and log end time of strategy
        self.end_time = dt.datetime.now(dt.UTC)
        log_msg = f"Strategy finished at: {self.end_time}"
        self.log.info(log_msg)

        # Log count of processed bars
        log_msg = f"Total bars processed: {self.bars_processed}"
        self.log.info(log_msg)
