"""
Unit and Integration Tests for BhavFnO Expiry & Analytics Engine.
============================================================
"""

import unittest
from datetime import datetime
import zoneinfo

from institutional_integrations.bhavfno_engine import (
    BhavFnOEngine,
    BhavFnOBrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER_BHAVFNO,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


class TestBhavFnOEngine(unittest.TestCase):

    def setUp(self) -> None:
        self.engine = BhavFnOEngine()
        self.adapter = BhavFnOBrokerAdapter()

    def test_round_tick_005(self) -> None:
        self.assertEqual(round_tick_005(100.02), 100.00)
        self.assertEqual(round_tick_005(100.03), 100.05)
        self.assertEqual(round_tick_005(100.07), 100.05)

    def test_calculate_monthly_expiries(self) -> None:
        expiries = self.engine.calculate_monthly_expiries(2025)
        self.assertEqual(len(expiries), 13)
        self.assertEqual(expiries[1], "30-01-2025")  # Last Thursday of Jan 2025

    def test_compute_bhav_iv_pcr(self) -> None:
        ce_records = [{"strike": 25000, "oi": 10000, "iv": 15.0}]
        pe_records = [{"strike": 25000, "oi": 12000, "iv": 16.0}]

        res = self.engine.compute_bhav_iv_pcr(ce_records, pe_records)
        self.assertEqual(res["magic_number"], MAGIC_NUMBER_BHAVFNO)
        self.assertEqual(res["pcr"], 1.2)
        self.assertEqual(res["bias"], "BULLISH_PCR")

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

        import institutional_integrations.bhavfno_engine as mod
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
        registered = IndianBrokerPluginRegistry.get_adapter_class("BHAVFNO")
        self.assertIsNotNone(registered)


if __name__ == "__main__":
    unittest.main()
