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
from unittest.mock import patch

import sizing


class SizingSafetyTests(unittest.TestCase):
    def test_unknown_regime_fails_closed_and_does_not_emit_quantity(self):
        with patch.object(
            sizing, "_regime_scale", return_value=(0.0, "UNKNOWN", "regime unavailable")
        ):
            out = sizing.suggest("ABC", trigger=100, stop=95, capital=100000)
        self.assertIsNone(out["p_win"])
        self.assertFalse(out["actionable"])
        self.assertNotIn("shares", out)
        self.assertEqual(out["reason"], "regime unavailable")

    def test_caps_apply_after_quality_and_regime_multipliers(self):
        with patch.object(sizing, "_regime_scale", return_value=(0.5, "WEAK", None)):
            out = sizing.suggest("ABC", trigger=100, stop=95, capital=100000, shape_score=80)
        self.assertIsNone(out["kelly_pct"])
        self.assertLessEqual(out["actual_alloc_pct"], 25.0)
        self.assertLessEqual(out["actual_planned_risk_pct"], 1.0)
        self.assertTrue(out["actionable"])

    def test_invalid_prices_are_not_actionable(self):
        with patch.object(sizing, "_regime_scale", return_value=(1.0, "BULL", None)):
            out = sizing.suggest("ABC", trigger=100, stop=100, capital=100000)
        self.assertFalse(out["actionable"])
        self.assertIn("above stop", out["reason"])


if __name__ == "__main__":
    unittest.main()
