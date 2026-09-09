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


import random
import unittest
from unittest.mock import MagicMock

from src.broker import BrokerBuilder, Order, OrderType


def generate_fake_quotes(symbols, date):
    quotes = []
    for symbol in symbols:
        price = random.randint(10, 20)
        quote_dict = {
            "bid": price,
            "bid_volume": random.randint(100, 1000),
            "ask": price + 1,
            "ask_volume": random.randint(100, 1000),
            "date": date,
            "symbol": symbol,
        }
        quotes.append(quote_dict)
    return {"quotes": quotes}


class TestBroker(unittest.TestCase):
    def test_main_loop(self):
        http_client = MagicMock()

        http_client.init.return_value = {"backtest_id": 0}
        http_client.fetch_quotes.side_effect = [
            generate_fake_quotes(["ABC"], 100),
            generate_fake_quotes(["ABC"], 101),
        ]
        http_client.tick.return_value = {
            "has_next": False,
            "executed_trades": [],
            "inserted_orders": [],
        }

        builder = BrokerBuilder()
        builder.init_cash(1000)
        builder.init_dataset_name("Test")
        builder.init_http(http_client)
        brkr = builder.build()

        order = Order(OrderType.MarketBuy, "ABC", 100, None)
        brkr.insert_order(order)

        brkr.tick()
