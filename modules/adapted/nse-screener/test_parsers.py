"""Regression tests for the two parsers that have already bitten us once.

    .venv/bin/python -m unittest discover tests
"""
import unittest

import pandas as pd

from ingest.corporate_actions import factor
from ingest.financials import parse_xbrl


class TestCAFactor(unittest.TestCase):
    def test_modern_split_wording(self):
        self.assertAlmostEqual(factor(
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share "
            "To Re 1/- Per Share"), 0.1)

    def test_abbreviated_split_wording(self):        # pre-2018 records
        self.assertAlmostEqual(factor(" Fv Splt Frm Rs 10 To Re 1"), 0.1)

    def test_bonus(self):
        self.assertAlmostEqual(factor("Bonus 1:1"), 0.5)
        self.assertAlmostEqual(factor("Bonus 1:2"), 2 / 3)
        self.assertAlmostEqual(factor(" Bonus 17:25"), 25 / 42)

    def test_dividend_is_not_adjusting(self):
        self.assertEqual(factor("Dividend - Rs 5 Per Share"), 1.0)
        self.assertEqual(factor("Annual General Meeting"), 1.0)

    def test_split_and_bonus_combined(self):
        f = factor("Face Value Split From Rs 10 To Re 1 / Bonus 1:1")
        self.assertAlmostEqual(f, 0.05)


XBRL_ONED = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in="http://taxonomy/in">
  <in:ProfitLossForPeriod contextRef="OneD">1234.5</in:ProfitLossForPeriod>
  <in:ProfitLossForPeriod contextRef="FourD">9999.9</in:ProfitLossForPeriod>
  <in:BasicEarningsLossPerShare contextRef="OneD">2.5</in:BasicEarningsLossPerShare>
</xbrl>"""

XBRL_BANKING = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in="http://taxonomy/in-bank">
  <in:ProfitLossForThePeriod contextRef="OneD">74164800000</in:ProfitLossForThePeriod>
</xbrl>"""

XBRL_DECLARED = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in="http://taxonomy/in">
  <context id="Q">
    <period><startDate>2024-01-01</startDate><endDate>2024-03-31</endDate></period>
  </context>
  <context id="Y">
    <period><startDate>2023-04-01</startDate><endDate>2024-03-31</endDate></period>
  </context>
  <in:ProfitLossForPeriod contextRef="Y">8888.0</in:ProfitLossForPeriod>
  <in:ProfitLossForPeriod contextRef="Q">1111.0</in:ProfitLossForPeriod>
</xbrl>"""


class TestXBRL(unittest.TestCase):
    def test_oned_convention_wins(self):
        """Legacy NSE files reference OneD without declaring it."""
        out = parse_xbrl(XBRL_ONED, pd.Timestamp("2024-03-31"))
        self.assertEqual(out["net_profit"], 1234.5)   # NOT the FourD YTD
        self.assertEqual(out["eps"], 2.5)

    def test_declared_context_fallback_picks_quarter_not_year(self):
        out = parse_xbrl(XBRL_DECLARED, pd.Timestamp("2024-03-31"))
        self.assertEqual(out["net_profit"], 1111.0)   # ~90-day duration only

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_xbrl(b"not xml at all", pd.Timestamp("2024-03-31")))

    def test_banking_taxonomy_the_period(self):
        """Banks file 'ProfitLossForThePeriod' — one extra word, 18% parse
        rate before the fix. HDFC Bank Q3 FY20 real value."""
        out = parse_xbrl(XBRL_BANKING, pd.Timestamp("2019-12-31"))
        self.assertEqual(out["net_profit"], 74164800000.0)


if __name__ == "__main__":
    unittest.main()
