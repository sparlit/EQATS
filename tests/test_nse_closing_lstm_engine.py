"""
Unit and Integration Tests for NSE Closing Stock Price Prediction LSTM Engine.
==========================================================================
"""

import unittest
from datetime import datetime
import zoneinfo

from institutional_integrations.nse_closing_lstm_engine import (
    NSEClosingLSTMEngine,
    NSEClosingLSTMBrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER_NSE_CLOSING_LSTM,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


class TestNSEClosingLSTMEngine(unittest.TestCase):

    def setUp(self) -> None:
        self.engine = NSEClosingLSTMEngine(lookback_window=60)
        self.adapter = NSEClosingLSTMBrokerAdapter()

    def test_round_tick_005(self) -> None:
        self.assertEqual(round_tick_005(100.02), 100.00)
        self.assertEqual(round_tick_005(100.03), 100.05)
        self.assertEqual(round_tick_005(100.07), 100.05)

    def test_predict_next_close(self) -> None:
        prices = [100.0 + i * 0.5 for i in range(20)]
        res = self.engine.predict_next_close(prices)
        self.assertEqual(res["magic_number"], MAGIC_NUMBER_NSE_CLOSING_LSTM)
        self.assertIn("predicted_close", res)
        self.assertIn("signal", res)

    def test_predict_next_close_insufficient_data(self) -> None:
        res = self.engine.predict_next_close([100.0, 101.0])
        self.assertEqual(res["predicted_close"], 0.0)
        self.assertEqual(res["signal"], "NEUTRAL")

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

        import institutional_integrations.nse_closing_lstm_engine as mod
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
        registered = IndianBrokerPluginRegistry.get_adapter_class("NSE_CLOSING_LSTM")
        self.assertIsNotNone(registered)


if __name__ == "__main__":
    unittest.main()
