"""
Unit Tests for K.I.T. Bot Engine.
Verifies Pine Script v5 generation, social signal parsing, and autopilot mode threshold checks.
"""
from typing import Any
import unittest
from institutional_integrations.kit_bot_engine import KitPineScriptGenerator, KitSocialSignalParser, KitAutopilotManager, KitAutopilotMode

class TestKitBotEngine(unittest.TestCase):

    def test_pine_script_generator(self) -> None:
        gen = KitPineScriptGenerator()
        indicator_code = gen.generate_indicator(name='Test RSI', period=14)
        self.assertIn('//@version=5', indicator_code)
        self.assertIn('ta.rsi', indicator_code)
        strategy_code = gen.generate_strategy(name='EMA Strategy', fast_ema=9, slow_ema=21)
        self.assertIn('strategy(', strategy_code)
        self.assertIn('ta.crossover', strategy_code)

    def test_social_signal_parser(self) -> None:
        parser = KitSocialSignalParser()
        text = 'BUY EURUSD ENTRY: 1.1000 SL: 1.0950 TP: 1.1100'
        sig = parser.parse_text_signal(text)
        self.assertIsNotNone(sig)
        if sig is not None:
            self.assertEqual(sig.symbol, 'EURUSD')
            self.assertEqual(sig.direction, 'BUY')
            self.assertEqual(sig.entry_price, 1.1)
            self.assertEqual(sig.stop_loss, 1.095)
            self.assertEqual(sig.take_profit, 1.11)
        self.assertIsNone(parser.parse_text_signal('Hello world no signal here'))

    def test_autopilot_manager(self) -> None:
        mgr = KitAutopilotManager(mode=KitAutopilotMode.SEMI_AUTO, approval_threshold_usd=500.0)
        dec1 = mgr.evaluate_order_gate('EURUSD', 'BUY', 300.0)
        self.assertTrue(dec1.approved)
        self.assertFalse(dec1.requires_manual_approval)
        dec2 = mgr.evaluate_order_gate('EURUSD', 'BUY', 800.0)
        self.assertFalse(dec2.approved)
        self.assertTrue(dec2.requires_manual_approval)
        mgr.activate_kill_switch()
        dec3 = mgr.evaluate_order_gate('EURUSD', 'BUY', 100.0)
        self.assertFalse(dec3.approved)
        self.assertIn('kill switch', dec3.reason)
if __name__ == '__main__':
    unittest.main()
