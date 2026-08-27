"""
EQATS Version 8.7 Institutional Upgrade Verification Suite
Verifies version assertions, ScalperBrain v8.7 attributes, and AatEAv13 risk-free entry adaptations.
"""

import pytest
import brain
from brain import ScalperBrain


def test_v8_7_version_assertions():
    scalper = ScalperBrain()
    assert scalper.version == "8.7.0"


def test_v8_7_brain_evaluation_and_slippage_control():
    scalper = ScalperBrain()
    bars = [
        {"open": 1.1000 + i*0.0001, "high": 1.1005 + i*0.0001, "low": 1.0995 + i*0.0001, "close": 1.1002 + i*0.0001, "tick_volume": 1000}
        for i in range(250)
    ]
    res = scalper.evaluate("EURUSD", bars, current_equity=10000.0)
    assert "decision" in res
    assert "v8_7_slippage_pips" in res
    assert res["v8_7_slippage_pips"] >= 0.5
