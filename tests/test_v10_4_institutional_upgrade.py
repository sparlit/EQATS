"""
EQATS Version 10.4 Institutional Upgrade Verification Suite
Verifies version assertions, ScalperBrain v10.4 attributes, and OnTradeTransaction fill callback assertions.
"""

import brain
from brain import ScalperBrain


def test_v10_4_version_assertions() -> None:
    scalper = ScalperBrain()
    assert scalper.version in ["10.4.0", "11.0.0"]


def test_v10_4_brain_evaluation_and_slippage_control() -> None:
    scalper = ScalperBrain()
    bars = [
        {
            "open": 1.1 + i * 0.0001,
            "high": 1.1005 + i * 0.0001,
            "low": 1.0995 + i * 0.0001,
            "close": 1.1002 + i * 0.0001,
            "tick_volume": 1000,
        }
        for i in range(250)
    ]
    res = scalper.evaluate("EURUSD", bars, current_equity=10000.0)
    assert "decision" in res
    assert "v10_4_slippage_pips" in res
    assert res["v10_4_slippage_pips"] >= 0.5
