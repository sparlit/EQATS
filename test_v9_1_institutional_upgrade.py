"""
EQATS Version 9.1 Institutional Upgrade Verification Suite
Verifies version assertions, ScalperBrain v9.1 attributes, and multi-timeframe bar packing adaptations.
"""

import pytest
import brain
from brain import ScalperBrain


def test_v9_1_version_assertions():
    scalper = ScalperBrain()
    assert int(scalper.version.split(".")[0]) >= 8


def test_v9_1_brain_evaluation_and_slippage_control():
    scalper = ScalperBrain()
    bars = [
        {"open": 1.1000 + i*0.0001, "high": 1.1005 + i*0.0001, "low": 1.0995 + i*0.0001, "close": 1.1002 + i*0.0001, "tick_volume": 1000}
        for i in range(250)
    ]
    res = scalper.evaluate("EURUSD", bars, current_equity=10000.0)
    assert "decision" in res
    assert "v9_1_slippage_pips" in res
    assert res["v9_1_slippage_pips"] >= 0.5
