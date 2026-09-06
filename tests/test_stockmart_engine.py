"""
Unit and Integration Tests for StockMart Simulation Engine.
=========================================================
"""

import unittest
from datetime import datetime
import zoneinfo

from institutional_integrations.stockmart_engine import (
    StockMartEngine,
    StockMartBrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER_STOCKMART,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


class TestStockMartEngine(unittest.TestCase):

    def setUp(self) -> None:
        self.engine = StockMartEngine(initial_cash=1000000.0)
        self.adapter = StockMartBrokerAdapter()

    def test_round_tick_005(self) -> None:
        self.assertEqual(round_tick_005(100.02), 100.00)
        self.assertEqual(round_tick_005(100.03), 100.05)
        self.assertEqual(round_tick_005(100.07), 100.05)

    def test_add_limit_order_and_matching(self) -> None:
        res_ask = self.engine.add_limit_order("RELIANCE", "SELL", 2500.00, 10)
        self.assertEqual(res_ask["asks_count"], 1)

        res_bid = self.engine.add_limit_order("RELIANCE", "BUY", 2500.00, 10)
        self.assertEqual(len(res_bid["matched_trades"]), 1)
        self.assertEqual(res_bid["matched_trades"][0]["price"], 2500.00)
        self.assertEqual(res_bid["matched_trades"][0]["quantity"], 10)

    def test_portfolio_equity_evaluation(self) -> None:
        self.engine.positions = {"RELIANCE": 10, "INFY": 20}
        prices = {"RELIANCE": 2500.0, "INFY": 1500.0}
        eval_res = self.engine.evaluate_portfolio_equity(prices)

        self.assertEqual(eval_res["magic_number"], MAGIC_NUMBER_STOCKMART)
        self.assertEqual(eval_res["cash"], 1000000.0)
        self.assertEqual(eval_res["position_value"], 55000.0)
        self.assertEqual(eval_res["total_equity"], 1055000.0)

    def test_is_ist_market_open(self) -> None:
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        open_dt = datetime(2025, 1, 15, 11, 0, 0, tzinfo=ist_tz)  # Wednesday 11:00 AM
        closed_dt = datetime(2025, 1, 15, 18, 0, 0, tzinfo=ist_tz)  # Wednesday 6:00 PM
        weekend_dt = datetime(2025, 1, 18, 11, 0, 0, tzinfo=ist_tz)  # Saturday 11:00 AM

        self.assertTrue(is_ist_market_open(open_dt))
        self.assertFalse(is_ist_market_open(closed_dt))
        self.assertFalse(is_ist_market_open(weekend_dt))

    def test_adapter_connectivity(self) -> None:
        self.assertTrue(self.adapter.connect())
        self.assertTrue(self.adapter.is_connected())
        self.assertTrue(self.adapter.disconnect())
        self.assertFalse(self.adapter.is_connected())

    def test_adapter_order_execution(self) -> None:
        self.adapter.connect()
        req = SEBIOrderRequest(
            symbol="RELIANCE",
            order_type="BUY",
            quantity=10,
            price=2500.03,
            product="CNC",
            exchange="NSE",
        )

        import institutional_integrations.stockmart_engine as mod
        original_func = mod.is_ist_market_open
        try:
            mod.is_ist_market_open = lambda now_dt=None: True
            res = self.adapter.execute_order(req)
            self.assertTrue(res.success)
            self.assertEqual(res.price, 2500.05)
            self.assertEqual(res.status, "FILLED")
        finally:
            mod.is_ist_market_open = original_func

    def test_registry(self) -> None:
        registered = IndianBrokerPluginRegistry.get_adapter_class("STOCKMART")
        self.assertIsNotNone(registered)


if __name__ == "__main__":
    unittest.main()
