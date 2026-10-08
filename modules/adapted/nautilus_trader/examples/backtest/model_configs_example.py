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
Example of model configs.
"""

from decimal import Decimal

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.common import LogLevel
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    LoggerConfig,
)
from nautilus_trader.execution import (
    FixedFeeModel,
    MakerTakerFeeModel,
    PerContractFeeModel,
    ProbabilisticFillModel,
    StaticLatencyModel,
)
from nautilus_trader.model import (
    AccountType,
    BookType,
    InstrumentId,
    Money,
    NautilusDataType,
    OmsType,
    TraderId,
)

if __name__ == "__main__":
    # Configure backtest engine
    engine_config = BacktestEngineConfig(
        trader_id=TraderId("BACKTESTER-001"),
        logging=LoggerConfig(stdout_level=LogLevel.INFO),
    )

    fill_model = ProbabilisticFillModel(
        prob_fill_on_limit=0.95,
        prob_slippage=0.05,
        random_seed=42,
    )

    latency_model = StaticLatencyModel(
        base_latency_nanos=5_000_000,
        insert_latency_nanos=2_000_000,
        update_latency_nanos=3_000_000,
        cancel_latency_nanos=1_000_000,
    )

    maker_taker_fee_model = MakerTakerFeeModel(
        maker_rate=Decimal("0.0001"),
        taker_rate=Decimal("0.0002"),
    )
    fixed_fee_model = FixedFeeModel(
        commission=Money.from_str("1.50 USD"),
        charge_commission_once=True,
    )
    per_contract_fee_model = PerContractFeeModel(
        commission=Money.from_str("0.01 USD"),
    )
    recurring_fixed_fee_model = FixedFeeModel(
        commission=Money.from_str("2.00 USD"),
        charge_commission_once=False,
    )

    # Create venue configs with different models
    venue_config1 = BacktestVenueConfig(
        name="NASDAQ",
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=["1000000 USD"],
        book_type=BookType.L1_MBP,
        fill_model=fill_model,
        latency_model=latency_model,
        fee_model=maker_taker_fee_model,
    )

    venue_config2 = BacktestVenueConfig(
        name="NYSE",
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=["1000000 USD"],
        book_type=BookType.L1_MBP,
        fill_model=fill_model,
        latency_model=latency_model,
        fee_model=fixed_fee_model,
    )

    venue_config3 = BacktestVenueConfig(
        name="CME",
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=["1000000 USD"],
        book_type=BookType.L1_MBP,
        fill_model=fill_model,
        latency_model=latency_model,
        fee_model=per_contract_fee_model,
    )

    # Create venue config with custom fixed fee model
    venue_config4 = BacktestVenueConfig(
        name="BATS",
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=["1000000 USD"],
        book_type=BookType.L1_MBP,
        fill_model=fill_model,
        latency_model=latency_model,
        fee_model=recurring_fixed_fee_model,
    )

    # Create data config (this is just a placeholder - you would need actual data)
    data_config = BacktestDataConfig(
        data_type=NautilusDataType.QuoteTick,
        catalog_path="./data",
        instrument_id=InstrumentId.from_str("AAPL.NASDAQ"),
    )

    # Create BacktestRunConfig
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config1, venue_config2, venue_config3, venue_config4],
        data=[data_config],
    )

    # Create and run the backtest node
    node = BacktestNode([run_config])

    # Note: This example won't actually run without proper data
    # results = node.run()

    print("Example of passing model objects to BacktestVenueConfig")
    print(f"Venue 1 fee model: {venue_config1.fee_model}")
    print(f"Venue 2 fee model: {venue_config2.fee_model}")
    print(f"Venue 3 fee model: {venue_config3.fee_model}")
    print(f"Venue 4 fee model: {venue_config4.fee_model}")
    print(f"Fill model: {venue_config1.fill_model}")
    print(f"Latency model: {venue_config1.latency_model}")
