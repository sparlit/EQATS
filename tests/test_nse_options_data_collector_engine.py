"""
Unit and Integration Tests for NSE Options Data Collector Engine.
============================================================
"""

import unittest
from datetime import datetime
import zoneinfo

from institutional_integrations.nse_options_data_collector_engine import (
    NSEOptionsDataCollectorEngine,
    NSEOptionsDataCollectorBrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER_NSE_OPTIONS_DATA_COLLECTOR,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


class TestNSEOptionsDataCollectorEngine(unittest.TestCase):

    def setUp(self) -> None:
        self.engine = NSEOptionsDataCollectorEngine()
        self.adapter = NSEOptionsDataCollectorBrokerAdapter()

    def test_round_tick_005(self) -> None:
        self.assertEqual(round_tick_005(100.02), 100.00)
        self.assertEqual(round_tick_005(100.03), 100.05)
        self.assertEqual(round_tick_005(100.07), 100.05)

    def test_process_oi_snapshot(self) -> None:
        records = [
            {"strike": 25000, "call_oi": 10000, "put_oi": 15000},
            {"strike": 25100, "call_oi": 20000, "put_oi": 18000},
        ]
        res = self.engine.process_oi_snapshot(records)
        self.assertEqual(res["magic_number"], MAGIC_NUMBER_NSE_OPTIONS_DATA_COLLECTOR)
        self.assertEqual(res["total_call_oi"], 30000)
        self.assertEqual(res["total_put_oi"], 33000)
        self.assertEqual(res["pcr"], 1.1)

    def test_analyze_premarket_gap(self) -> None:
        res_up = self.engine.analyze_premarket_gap(25000.0, 25200.0)
        self.assertEqual(res_up["gap_type"], "GAP_UP")
        self.assertEqual(res_up["gap_percent"], 0.8)

        res_down = self.engine.analyze_premarket_gap(25000.0, 24800.0)
        self.assertEqual(res_down["gap_type"], "GAP_DOWN")

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
            symbol="NIFTY",
            order_type="BUY",
            quantity=50,
            price=25000.03,
            product="NRML",
            exchange="NFO",
        )

        import institutional_integrations.nse_options_data_collector_engine as mod
        original_func = mod.is_ist_market_open
        try:
            mod.is_ist_market_open = lambda now_dt=None: True
            res = self.adapter.execute_order(req)
            self.assertTrue(res.success)
            self.assertEqual(res.price, 25000.05)
            self.assertEqual(res.status, "FILLED")
        finally:
            mod.is_ist_market_open = original_func

    def test_registry(self) -> None:
        registered = IndianBrokerPluginRegistry.get_adapter_class("NSE_OPTIONS_DATA_COLLECTOR")
        self.assertIsNotNone(registered)


if __name__ == "__main__":
    unittest.main()
