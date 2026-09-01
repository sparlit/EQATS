"""
Unit Tests for Finterion Adapter Engine.
Verifies portfolio synchronization, order execution routing, and health check heartbeats.
"""
from typing import Any
import unittest
from institutional_integrations.finterion_adapter import FinterionPortfolioProvider, FinterionOrderExecutor, FinterionPingHook, FinterionOrderRequest

class TestFinterionAdapter(unittest.TestCase):

    def test_finterion_portfolio_provider_sync(self) -> None:
        provider = FinterionPortfolioProvider(account_id='ACC_9988', base_currency='USD')
        open_trades = [{'symbol': 'EURUSD', 'lot_size': 0.1, 'open_price': 1.1, 'direction': 'BUY'}, {'symbol': 'GBPUSD', 'lot_size': 0.05, 'open_price': 1.25, 'direction': 'SELL'}]
        prices = {'EURUSD': 1.102, 'GBPUSD': 1.248}
        portfolio = provider.sync_portfolio(current_balance=10000.0, open_trades=open_trades, current_prices=prices)
        self.assertEqual(portfolio.account_id, 'ACC_9988')
        self.assertEqual(portfolio.currency, 'USD')
        self.assertEqual(len(portfolio.positions), 2)
        self.assertGreater(portfolio.total_equity, 10000.0)

    def test_finterion_order_executor(self) -> None:
        executor = FinterionOrderExecutor(api_key='TEST_KEY')
        req = FinterionOrderRequest(symbol='EURUSD', order_type='BUY', amount=0.1, price=1.1, stop_loss=1.095, take_profit=1.11)
        res = executor.execute_order(req)
        self.assertEqual(res.status, 'EXECUTED')
        self.assertEqual(res.symbol, 'EURUSD')
        self.assertEqual(res.filled_amount, 0.1)
        self.assertTrue(res.order_id.startswith('FINT_'))
        req_invalid = FinterionOrderRequest(symbol='EURUSD', order_type='BUY', amount=0.0, price=1.1)
        res_invalid = executor.execute_order(req_invalid)
        self.assertEqual(res_invalid.status, 'REJECTED')

    def test_finterion_ping_hook(self) -> None:
        hook = FinterionPingHook('EQATS_v10_4')
        ping = hook.emit_ping(status='ACTIVE', active_strategy='VOTING_ENSEMBLE')
        self.assertEqual(ping['algorithm_id'], 'EQATS_v10_4')
        self.assertEqual(ping['status'], 'ACTIVE')
        self.assertEqual(ping['active_strategy'], 'VOTING_ENSEMBLE')
        self.assertEqual(ping['ping_count'], 1)
if __name__ == '__main__':
    unittest.main()
