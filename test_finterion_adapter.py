"""
Unit Tests for Finterion Adapter Engine.
Verifies portfolio synchronization, order execution routing, and health check heartbeats.
"""

import unittest
from institutional_integrations.finterion_adapter import (
    FinterionPortfolioProvider,
    FinterionOrderExecutor,
    FinterionPingHook,
    FinterionOrderRequest,
)


class TestFinterionAdapter(unittest.TestCase):

    def test_finterion_portfolio_provider_sync(self):
        provider = FinterionPortfolioProvider(account_id="ACC_9988", base_currency="USD")
        open_trades = [
            {"symbol": "EURUSD", "lot_size": 0.1, "open_price": 1.1000, "direction": "BUY"},
            {"symbol": "GBPUSD", "lot_size": 0.05, "open_price": 1.2500, "direction": "SELL"},
        ]
        prices = {"EURUSD": 1.1020, "GBPUSD": 1.2480}

        portfolio = provider.sync_portfolio(
            current_balance=10000.0,
            open_trades=open_trades,
            current_prices=prices,
        )

        self.assertEqual(portfolio.account_id, "ACC_9988")
        self.assertEqual(portfolio.currency, "USD")
        self.assertEqual(len(portfolio.positions), 2)
        self.assertGreater(portfolio.total_equity, 10000.0)

    def test_finterion_order_executor(self):
        executor = FinterionOrderExecutor(api_key="TEST_KEY")
        req = FinterionOrderRequest(
            symbol="EURUSD",
            order_type="BUY",
            amount=0.1,
            price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )

        res = executor.execute_order(req)
        self.assertEqual(res.status, "EXECUTED")
        self.assertEqual(res.symbol, "EURUSD")
        self.assertEqual(res.filled_amount, 0.1)
        self.assertTrue(res.order_id.startswith("FINT_"))

        # Test rejected order
        req_invalid = FinterionOrderRequest(
            symbol="EURUSD",
            order_type="BUY",
            amount=0.0,
            price=1.1000,
        )
        res_invalid = executor.execute_order(req_invalid)
        self.assertEqual(res_invalid.status, "REJECTED")

    def test_finterion_ping_hook(self):
        hook = FinterionPingHook("EQATS_v10_4")
        ping = hook.emit_ping(status="ACTIVE", active_strategy="VOTING_ENSEMBLE")

        self.assertEqual(ping["algorithm_id"], "EQATS_v10_4")
        self.assertEqual(ping["status"], "ACTIVE")
        self.assertEqual(ping["active_strategy"], "VOTING_ENSEMBLE")
        self.assertEqual(ping["ping_count"], 1)


if __name__ == "__main__":
    unittest.main()
