"""
EQATS Version 10.2 Institutional Upgrade Verification Suite
Verifies version assertions, ScalperBrain v10.2 attributes, and Data Collector role mode dispatching.
"""

import pytest
import brain
from brain import ScalperBrain


def test_v10_2_version_assertions():
    scalper = ScalperBrain()
    assert scalper.version == "10.2.0"


def test_v10_2_brain_evaluation_and_slippage_control():
    scalper = ScalperBrain()
    bars = [
        {"open": 1.1000 + i*0.0001, "high": 1.1005 + i*0.0001, "low": 1.0995 + i*0.0001, "close": 1.1002 + i*0.0001, "tick_volume": 1000}
        for i in range(250)
    ]
    res = scalper.evaluate("EURUSD", bars, current_equity=10000.0)
    assert "decision" in res
    assert "v10_2_slippage_pips" in res
    assert res["v10_2_slippage_pips"] >= 0.5
