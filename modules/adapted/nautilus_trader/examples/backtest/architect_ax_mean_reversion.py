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
Example of architect ax mean reversion.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    AssetClass,
    BarType,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    PerpetualContract,
    Price,
    Quantity,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.testkit.providers import TestDataProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "architect_ax"))

from strategies import BBMeanReversion, BBMeanReversionConfig

USD = Currency.from_str("USD")


# *** THIS IS A TEST STRATEGY WITH NO ALPHA ADVANTAGE WHATSOEVER. ***
# *** IT IS NOT INTENDED TO BE USED TO TRADE LIVE WITH REAL MONEY. ***

if __name__ == "__main__":
    instrument_id = InstrumentId.from_str("AUDUSD-PERP.AX")

    AUDUSD_PERP = PerpetualContract(
        instrument_id=instrument_id,
        raw_symbol=Symbol("AUDUSD-PERP"),
        underlying="AUD",
        asset_class=AssetClass.FX,
        quote_currency=USD,
        settlement_currency=USD,
        is_inverse=False,
        price_precision=5,
        size_precision=0,
        price_increment=Price.from_str("0.00001"),
        size_increment=Quantity.from_int(1),
        multiplier=Quantity.from_int(1000),
        lot_size=Quantity.from_int(1),
        margin_init=Decimal("0.05"),
        margin_maint=Decimal("0.025"),
        ts_event=0,
        ts_init=0,
    )

    ticks = TestDataProvider.quotes_from_truefx_csv(
        instrument=AUDUSD_PERP,
        csv_name="truefx/audusd-ticks.csv",
    )

    config = BacktestEngineConfig(trader_id=TraderId.from_str("BACKTESTER-001"))

    engine = BacktestEngine(config=config)

    AX = Venue("AX")
    engine.add_venue(
        venue=AX,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money.from_str("100000 USD")],
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal("0.0002"),
            taker_rate=Decimal("0.0005"),
        ),
    )

    engine.add_instrument(AUDUSD_PERP)
    engine.add_data(ticks)

    bar_type = BarType.from_str("AUDUSD-PERP.AX-1-MINUTE-MID-INTERNAL")

    strategy_config = BBMeanReversionConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        trade_size=Decimal(1),
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_buy_threshold=30.0,
        rsi_sell_threshold=70.0,
    )

    strategy = BBMeanReversion(config=strategy_config)
    engine.add_strategy(strategy)

    engine.run()

    with pd.option_context(
        "display.max_rows",
        100,
        "display.max_columns",
        None,
        "display.width",
        300,
    ):
        print(engine.generate_account_report(venue=AX))
        print(engine.generate_order_fills_report())
        print(engine.generate_positions_report())

    engine.reset()
    engine.dispose()
