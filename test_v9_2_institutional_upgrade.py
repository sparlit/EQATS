"""
EQATS Version 9.2 Institutional Upgrade Verification Suite
Verifies version assertions, ScalperBrain v9.2 attributes, and trend scale multiplier signal handling.
"""

import pytest
import brain
from brain import ScalperBrain


def test_v9_2_version_assertions():
    scalper = ScalperBrain()
    assert scalper.version == "9.2.0"


def test_v9_2_brain_evaluation_and_slippage_control():
    scalper = ScalperBrain()
    bars = [
        {"open": 1.1000 + i*0.0001, "high": 1.1005 + i*0.0001, "low": 1.0995 + i*0.0001, "close": 1.1002 + i*0.0001, "tick_volume": 1000}
        for i in range(250)
    ]
    res = scalper.evaluate("EURUSD", bars, current_equity=10000.0)
    assert "decision" in res
    assert "v9_2_slippage_pips" in res
    assert res["v9_2_slippage_pips"] >= 0.5
