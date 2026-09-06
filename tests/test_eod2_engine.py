"""
Unit and Integration Tests for EOD2 Relative Strength & Market Breadth Engine.
========================================================================
"""

import unittest
from datetime import datetime
import zoneinfo

from institutional_integrations.eod2_engine import (
    EOD2Engine,
    EOD2BrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER_EOD2,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


class TestEOD2Engine(unittest.TestCase):

    def setUp(self) -> None:
        self.engine = EOD2Engine(period=5)
        self.adapter = EOD2BrokerAdapter()

    def test_round_tick_005(self) -> None:
        self.assertEqual(round_tick_005(100.02), 100.00)
        self.assertEqual(round_tick_005(100.03), 100.05)
        self.assertEqual(round_tick_005(100.07), 100.05)

    def test_compute_dorsey_rs(self) -> None:
        rs = self.engine.compute_dorsey_rs(2500.0, 25000.0)
        self.assertEqual(rs, 10.0)

    def test_compute_mansfield_rs(self) -> None:
        stock_closes = [100.0, 102.0, 104.0, 106.0, 110.0]
        index_closes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]

        res = self.engine.compute_mansfield_rs(stock_closes, index_closes)
        self.assertEqual(res["magic_number"], MAGIC_NUMBER_EOD2)
        self.assertGreater(res["mansfield_rs"], 0.0)
        self.assertEqual(res["signal"], "MANSFIELD_BULLISH")

    def test_evaluate_market_breadth(self) -> None:
        snapshots = [
            {"close": 100.0, "ma50": 90.0, "ma200": 80.0, "high_52w": 100.0, "low_52w": 50.0},
            {"close": 200.0, "ma50": 210.0, "ma200": 190.0, "high_52w": 220.0, "low_52w": 150.0},
        ]
        res = self.engine.evaluate_market_breadth(snapshots)
        self.assertEqual(res["magic_number"], MAGIC_NUMBER_EOD2)
        self.assertEqual(res["pct_above_ma50"], 50.0)
        self.assertEqual(res["pct_above_ma200"], 100.0)
        self.assertEqual(res["new_52w_highs"], 1)

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

        import institutional_integrations.eod2_engine as mod
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
        registered = IndianBrokerPluginRegistry.get_adapter_class("EOD2")
        self.assertIsNotNone(registered)


if __name__ == "__main__":
    unittest.main()
