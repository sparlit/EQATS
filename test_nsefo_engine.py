"""
Unit Tests for NSEFO Derivatives & Probability Synthesis Engine.
Verifies Black-Scholes Greeks, conviction probability synthesis, and NLP order parsing.
"""

import unittest
from institutional_integrations.nsefo_engine import (
    NSeFoOptionGreeksCalculator,
    NSeFoProbabilitySynthesis,
    NSeFoNlpCommandParser,
)


class TestNSeFoEngine(unittest.TestCase):

    def test_greeks_calculator(self):
        calc = NSeFoOptionGreeksCalculator()
        greeks = calc.calculate_greeks(
            spot=24500.0,
            strike=24500.0,
            time_to_expiry_years=7.0 / 365.0,
            risk_free_rate=0.0695,
            volatility_iv=0.18,
            option_type="CE",
        )

        self.assertGreater(greeks.delta, 0.40)
        self.assertLess(greeks.delta, 0.60)
        self.assertGreater(greeks.gamma, 0.0)
        self.assertLess(greeks.theta, 0.0)
        self.assertGreater(greeks.vega, 0.0)

    def test_probability_synthesis(self):
        synth = NSeFoProbabilitySynthesis()
        prob = synth.calculate_winning_probability(trend_score=1.0, momentum_score=1.0, volatility_factor=1.0)
        self.assertGreater(prob, 0.8)

        prob_bear = synth.calculate_winning_probability(trend_score=-1.0, momentum_score=-1.0, volatility_factor=1.0)
        self.assertLess(prob_bear, 0.2)

    def test_nlp_command_parser(self):
        parser = NSeFoNlpCommandParser()
        cmd = parser.parse_command("Buy Nifty 24500 ce")

        self.assertIsNotNone(cmd)
        if cmd is not None:
            self.assertEqual(cmd.action, "BUY")
            self.assertEqual(cmd.symbol, "NIFTY")
            self.assertEqual(cmd.strike, 24500.0)
            self.assertEqual(cmd.option_type, "CE")

        # Invalid command
        self.assertIsNone(parser.parse_command("Random text without structure"))


if __name__ == "__main__":
    unittest.main()
