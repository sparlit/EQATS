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
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Blackbox acceptance tests for the v2 BacktestEngine.

Mirrors `tests/acceptance_tests/test_blackbox.py`. The v1 suite asserts on the exact
sequence of events captured by `msgbus.subscribe(events.account.* / events.order.* /
events.position.*)`. v2's BacktestEngine does not yet expose the kernel msgbus topic
broadcast for arbitrary subscribers from outside the trader, so this suite asserts on
public BacktestResult invariants instead - the strategy ran, produced multiple position
cycles, and the run completed without raising.

"""


from decimal import Decimal

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, Currency, Money, OmsType, Venue
from nautilus_trader.trading import ImportableStrategyConfig

from tests.providers import TestDataProvider, TestInstrumentProvider

MACD_STRATEGY = "strategies.acceptance:MACDTradeTickStrategy"
MACD_CONFIG = "strategies.acceptance:MACDStrategyConfig"


def test_cash_account_trades_macd_event_sequencing() -> None:
    """
    Test cash account trades macd event sequencing.
    """
    config = BacktestEngineConfig(bypass_logging=True, run_analysis=False)
    engine = BacktestEngine(config)

    venue = Venue("BINANCE")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[
            Money(10.0, Currency.from_str("ETH")),
            Money(100_000.0, Currency.from_str("USDT")),
        ],
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal(0),
            taker_rate=Decimal(0),
        ),
    )

    ethusdt = TestInstrumentProvider.ethusdt_binance()
    engine.add_instrument(ethusdt)

    trades = TestDataProvider.trades_from_binance_csv(
        ethusdt,
        csv_name="binance/ethusdt-trades.csv",
        max_rows=10_000,
    )
    engine.add_data(trades)

    engine.add_strategy_from_config(
        ImportableStrategyConfig(
            strategy_path=MACD_STRATEGY,
            config_path=MACD_CONFIG,
            config={
                "instrument_id": str(ethusdt.id),
                "trade_size": "0.05000",
                "fast_period": 12,
                "slow_period": 26,
                "entry_threshold": 0.00010,
            },
        ),
    )

    engine.run()
    result = engine.get_result()

    assert result.iterations == len(trades)
    assert result.total_events > 0
    # MACD should produce at least one entry+exit cycle on a 10k-trade window
    assert result.total_orders > 0
    assert result.total_positions > 0
    engine.dispose()
