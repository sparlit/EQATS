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
Example of databento test order book deltas.
"""

# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---


# %% [markdown]
# # Databento order-book deltas
#
# Load the tracked ESM4 MBO sample and replay it through the Rust-native book
# imbalance actor with an L3 matching engine.

# %%
from decimal import Decimal
from pathlib import Path

from nautilus_trader.adapters.databento import DatabentoDataLoader
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, BookType, Currency, Money, OmsType, TraderId, Venue
from nautilus_trader.trading import BookImbalanceActorConfig

# %%
if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[3]
    data_dir = repo_root / "test_data" / "databento" / "order_book_deltas_catalog" / "databento"
    loader = DatabentoDataLoader(
        repo_root / "crates" / "adapters" / "databento" / "publishers.json",
    )

    instruments = loader.load_instruments(
        data_dir / "orderbooks_definition.dbn.zst",
        use_exchange_as_venue=True,
    )
    deltas = loader.load_order_book_deltas(
        data_dir / "orderbooks_mbo_2024-05-08T00-00-00_2024-05-08T00-00-02.dbn.zst",
    )

    engine = BacktestEngine(
        BacktestEngineConfig(trader_id=TraderId.from_str("BACKTESTER-001")),
    )
    XCME = Venue("XCME")
    USD = Currency.from_str("USD")
    engine.add_venue(
        venue=XCME,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        book_type=BookType.L3_MBO,
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal(0),
            taker_rate=Decimal(0),
        ),
    )

    for instrument in instruments:
        engine.add_instrument(instrument)
    engine.add_data(deltas)
    engine.add_builtin_actor(
        "BookImbalanceActor",
        BookImbalanceActorConfig(
            instrument_ids=[instruments[0].id],
            log_interval=1_000,
        ),
    )
    engine.run()

    print(engine.get_result().summary)
    engine.reset()
    engine.dispose()
