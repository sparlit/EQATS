"""
Unit Tests for QuantStats Engine and SEBI Broker Adapter
======================================================
Tests QuantStats portfolio risk calculations, HTML report generation, signal processing,
order recommendation, and SEBI-compliant execution lifecycle.
"""

import os
import unittest
import pandas as pd
import numpy as np

from institutional_integrations.quantstats_engine import (
    MAGIC_NUMBER_QUANTSTATS,
    QuantStatsBrokerAdapter,
    QuantStatsEngine,
    is_ist_market_open,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


class TestQuantStatsEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = QuantStatsEngine(initial_capital=1000000.0, risk_free_rate=0.05)
        np.random.seed(42)
        dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
        returns_arr = np.random.normal(loc=0.001, scale=0.015, size=100)
        self.returns_series = pd.Series(returns_arr, index=dates)

        prices_arr = 100.0 * np.cumprod(1.0 + returns_arr)
        self.prices_series = pd.Series(prices_arr, index=dates)

    def test_round_tick_005(self) -> None:
        self.assertEqual(round_tick_005(100.02), 100.0)
        self.assertEqual(round_tick_005(100.03), 100.05)
        self.assertEqual(round_tick_005(100.07), 100.05)
        self.assertEqual(round_tick_005(100.08), 100.10)
        self.assertEqual(round_tick_005(0.0), 0.05)
        self.assertEqual(round_tick_005(-10.0), 0.05)

    def test_prepare_returns_series(self) -> None:
        s_ret = self.engine.prepare_returns_series(self.returns_series)
        self.assertIsInstance(s_ret, pd.Series)
        self.assertIsInstance(s_ret.index, pd.DatetimeIndex)

        s_prices = self.engine.prepare_returns_series(self.prices_series)
        self.assertIsInstance(s_prices, pd.Series)
        self.assertLess(s_prices.mean(), 1.0)  # Verify pct_change was applied

    def test_calculate_metrics(self) -> None:
        metrics = self.engine.calculate_metrics(self.returns_series)
        self.assertIn("sharpe_ratio", metrics)
        self.assertIn("sortino_ratio", metrics)
        self.assertIn("calmar_ratio", metrics)
        self.assertIn("max_drawdown", metrics)
        self.assertIn("cagr", metrics)
        self.assertIn("win_rate", metrics)
        self.assertIn("volatility", metrics)
        self.assertIn("value_at_risk_95", metrics)
        self.assertIn("cvar_95", metrics)
        self.assertIn("engine", metrics)

    def test_generate_html_report(self) -> None:
        report_path = "test_qs_report.html"
        try:
            out_path = self.engine.generate_html_report(
                self.returns_series, output_path=report_path, title="Test Report"
            )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("Test Report", content)
        finally:
            if os.path.exists(report_path):
                os.remove(report_path)

    def test_generate_order_recommendation(self) -> None:
        buy_rec = self.engine.generate_order_recommendation("RELIANCE", 0.8, 2500.0)
        self.assertEqual(buy_rec["action"], "BUY")
        self.assertGreater(buy_rec["quantity"], 0)
        self.assertEqual(buy_rec["magic_number"], MAGIC_NUMBER_QUANTSTATS)

        sell_rec = self.engine.generate_order_recommendation("RELIANCE", -0.8, 2500.0)
        self.assertEqual(sell_rec["action"], "SELL")
        self.assertEqual(sell_rec["quantity"], 0)

        hold_rec = self.engine.generate_order_recommendation("RELIANCE", 0.1, 2500.0)
        self.assertEqual(hold_rec["action"], "HOLD")
        self.assertEqual(hold_rec["quantity"], 0)


class TestQuantStatsBrokerAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = QuantStatsBrokerAdapter()
        self.adapter.connect()

    def test_registry(self) -> None:
        adapter_cls = IndianBrokerPluginRegistry.get_adapter_class("QUANTSTATS")
        self.assertEqual(adapter_cls, QuantStatsBrokerAdapter)

    def test_account_info(self) -> None:
        info = self.adapter.get_account_info()
        self.assertEqual(info["broker"], "QuantStatsBroker")
        self.assertTrue(info["connected"])
        self.assertEqual(info["magic_number"], MAGIC_NUMBER_QUANTSTATS)

    def test_execute_order(self) -> None:
        req = SEBIOrderRequest(
            symbol="TCS",
            quantity=10,
            price=3500.0,
            order_type="BUY",
            order_kind="LIMIT",
            product="CNC",
            exchange="NSE",
        )
        if is_ist_market_open():
            resp = self.adapter.execute_order(req)
            self.assertTrue(resp.success)
            self.assertEqual(resp.status, "FILLED")
            self.assertEqual(resp.instrument_token, MAGIC_NUMBER_QUANTSTATS)
        else:
            resp = self.adapter.execute_order(req)
            self.assertFalse(resp.success)
            self.assertEqual(resp.status, "REJECTED")


if __name__ == "__main__":
    unittest.main()
