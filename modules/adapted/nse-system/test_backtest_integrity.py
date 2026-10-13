import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


import unittest

import pandas as pd
import strategy_backtest as sandbox
from backtest import BacktestResult, Trade


class BacktestIntegrityTests(unittest.TestCase):
    def test_drawdown_uses_cumulative_sequence_equity(self):
        result = BacktestResult(
            initial_capital=100.0,
            trades=[
                Trade(
                    "A", "2026-01-01", "2026-01-02", "long", 100, 110, 90, 130, 0.10, 1, "target"
                ),
                Trade("A", "2026-01-03", "2026-01-04", "long", 100, 90, 90, 130, -0.10, 1, "stop"),
            ],
        )
        self.assertAlmostEqual(result.max_drawdown, 0.10, places=8)
        self.assertIn("not a portfolio", result.summary())

    def test_simulator_handles_gap_and_right_censoring(self):
        df = pd.DataFrame(
            {
                "Open": [100, 90, 100],
                "High": [101, 95, 101],
                "Low": [99, 89, 99],
                "Close": [100, 92, 100],
            }
        )
        self.assertEqual(sandbox._simulate(df, 1, 100, 95, 110, 2)[:2], ("LOSS", 90.0))
        outcome = sandbox._simulate(df, 1, 100, 80, 110, 5)
        self.assertEqual(outcome[0], "OPEN")

    def test_current_data_strategy_fields_are_rejected(self):
        err = sandbox._validate_strategy_sandbox(
            {
                "conditions": [{"field": "roce", "op": ">", "value": 10}],
            }
        )
        self.assertIn("point-in-time", err)

    def test_cache_key_contains_strategy_definition(self):
        left = sandbox._cache_key("x", 2, 5, 10, 0.05, 3, 30, {"conditions": []}, "data")
        right = sandbox._cache_key(
            "x", 2, 5, 10, 0.05, 3, 30, {"conditions": [{"field": "mom1"}]}, "data"
        )
        self.assertNotEqual(left, right)


if __name__ == "__main__":
    unittest.main()
