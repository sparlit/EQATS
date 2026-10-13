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
Print nested signal delivery for self-publication or fanout.

Run from the repository root:
    python/.venv/bin/python examples/backtest/signal_reentrancy.py fanout

"""

import argparse

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import DataActor, LogLevel, Signal
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig


class PublishingActor(DataActor):
    """
    Republish from the first subscriber to expose nested callback order.
    """

    def on_start(self) -> None:
        """
        Subscribe before the observing actor.
        """
        self.subscribe_signal("reentry", priority=100)

    def on_signal(self, signal: Signal) -> None:
        """
        Print callback boundaries and publish the inner signal.
        """
        print(f"A:{signal.value}:enter", flush=True)
        if signal.value == "outer":
            self.publish_signal("reentry", "inner", ts_event=2)
        print(f"A:{signal.value}:exit", flush=True)


class ObservingActor(DataActor):
    """
    Print delivery order for a second subscriber.
    """

    def on_start(self) -> None:
        """
        Subscribe after the publishing actor.
        """
        self.subscribe_signal("reentry", priority=10)

    def on_signal(self, signal: Signal) -> None:
        """
        Print the callback entry and exit.
        """
        print(f"B:{signal.value}:enter", flush=True)
        print(f"B:{signal.value}:exit", flush=True)


class InitialPublisher(DataActor):
    """
    Start publication after subscribers have started.
    """

    def on_start(self) -> None:
        """
        Publish the outer signal and print when it returns.
        """
        print("PUBLISHER: publish outer", flush=True)
        self.publish_signal("reentry", "outer", ts_event=1)
        print("PUBLISHER: publication returned", flush=True)


def main() -> None:
    """
    Run the selected signal delivery scenario.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("self", "fanout"), nargs="?", default="fanout")
    args = parser.parse_args()
    print(f"Scenario: {args.scenario}", flush=True)
    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.WARNING),
            run_analysis=False,
        ),
    )
    try:
        engine.add_actor(PublishingActor())
        if args.scenario == "fanout":
            engine.add_actor(ObservingActor())
        engine.add_actor(InitialPublisher())
        engine.run()
    finally:
        engine.dispose()
    print("Completed without a propagated runtime error", flush=True)


if __name__ == "__main__":
    main()
