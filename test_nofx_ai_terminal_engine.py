"""
Unit and Integration Tests for NoFx AI Trading Terminal & Runtime Disposer Engine.
Verifies preflight checks, position limits, leverage clamping, cooldowns, drawdown auto-close,
direction board analytics, and AI paper trails.
"""
from typing import Any
import unittest
from institutional_integrations.nofx_ai_terminal_engine import NoFxRiskRuntimeDisposer, NoFxMarketDirectionBoard, NoFxAiModelManager, NoFxAction, NoFxModelDecision, NoFxPositionLimitConfig

class TestNoFxAiTerminalEngine(unittest.TestCase):

    def test_nofx_preflight_check(self) -> None:
        disposer = NoFxRiskRuntimeDisposer()
        status = disposer.run_preflight_check('DeepSeek-R1', 1000.0, True, min_required_balance=12.0)
        self.assertTrue(status.is_ready)
        self.assertTrue(status.model_access_ok)
        self.assertTrue(status.account_balance_ok)
        self.assertTrue(status.exchange_connected)
        self.assertEqual(len(status.reasons), 0)
        status_fail = disposer.run_preflight_check('', 5.0, False, min_required_balance=12.0)
        self.assertFalse(status_fail.is_ready)
        self.assertFalse(status_fail.model_access_ok)
        self.assertFalse(status_fail.account_balance_ok)
        self.assertFalse(status_fail.exchange_connected)
        self.assertGreaterEqual(len(status_fail.reasons), 3)

    def test_nofx_evaluate_proposal_approved(self) -> None:
        disposer = NoFxRiskRuntimeDisposer(NoFxPositionLimitConfig(reentry_cooldown_seconds=0.0))
        decision = NoFxModelDecision(model_name='Claude-3.5-Sonnet', symbol='EURUSD', action=NoFxAction.BUY, confidence=0.8, reasoning_summary='Strong MACD momentum and RSI oversold rebound.', proposed_volume=0.05)
        clamped = disposer.evaluate_proposal(decision=decision, account_equity=10000.0, current_price=1.085, open_positions=[])
        self.assertTrue(clamped.approved)
        self.assertGreater(clamped.clamped_volume, 0.0)
        self.assertLessEqual(clamped.clamped_leverage, 10.0)
        self.assertEqual(clamped.symbol, 'EURUSD')
        self.assertEqual(clamped.action, NoFxAction.BUY)

    def test_nofx_one_position_per_symbol_rule(self) -> None:
        disposer = NoFxRiskRuntimeDisposer(NoFxPositionLimitConfig(reentry_cooldown_seconds=0.0))
        decision = NoFxModelDecision(model_name='GPT-4o', symbol='EURUSD', action=NoFxAction.BUY, confidence=0.9, reasoning_summary='Breakout above resistance.', proposed_volume=0.02)
        open_positions = [{'symbol': 'EURUSD', 'lot_size': 0.01}]
        clamped = disposer.evaluate_proposal(decision=decision, account_equity=10000.0, current_price=1.085, open_positions=open_positions)
        self.assertFalse(clamped.approved)
        self.assertIn('one position per symbol', clamped.veto_reason)

    def test_nofx_drawdown_autoclose(self) -> None:
        disposer = NoFxRiskRuntimeDisposer()
        auto_close, reason = disposer.check_drawdown_autoclose(symbol='BTCUSD', direction='BUY', open_price=60000.0, current_price=60100.0, lot_size=1.0, contract_multiplier=1.0)
        self.assertEqual(disposer.symbol_peak_profit['BTCUSD'], 100.0)
        auto_close_triggered, reason = disposer.check_drawdown_autoclose(symbol='BTCUSD', direction='BUY', open_price=60000.0, current_price=60060.0, lot_size=1.0, contract_multiplier=1.0)
        self.assertTrue(auto_close_triggered)
        self.assertIn('Drawdown auto-close triggered', reason)

    def test_nofx_market_direction_board(self) -> None:
        board = NoFxMarketDirectionBoard(['EURUSD', 'XAUUSD'])
        board.update_direction('EURUSD', 0.8)
        board.update_direction('EURUSD', 0.7)
        summary = board.get_market_direction_summary('EURUSD')
        self.assertEqual(summary['symbol'], 'EURUSD')
        self.assertEqual(summary['direction'], 'BUY')
        self.assertEqual(summary['bias_score'], 0.7)
        heatmap = board.get_liquidation_heatmap('XAUUSD', 2350.0)
        self.assertLess(heatmap['long_liq_cluster'], 2350.0)
        self.assertGreater(heatmap['short_liq_cluster'], 2350.0)

    def test_nofx_ai_model_manager_paper_trail(self) -> None:
        manager = NoFxAiModelManager()
        dec1 = NoFxModelDecision(model_name='Qwen-Max', symbol='GBPUSD', action=NoFxAction.BUY, confidence=0.85, reasoning_summary='Supertrend trend alignment.')
        manager.record_decision(dec1)
        manager.record_trade_result('Qwen-Max', 150.0)
        manager.record_trade_result('DeepSeek-R1', 230.0)
        trail = manager.get_paper_trail('GBPUSD')
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0]['model_name'], 'Qwen-Max')
        leaderboard = manager.get_leaderboard()
        self.assertEqual(leaderboard[0]['model_name'], 'DeepSeek-R1')
        self.assertEqual(leaderboard[0]['realized_return_usd'], 230.0)
        self.assertEqual(leaderboard[1]['model_name'], 'Qwen-Max')
        self.assertEqual(leaderboard[1]['realized_return_usd'], 150.0)
if __name__ == '__main__':
    unittest.main()
