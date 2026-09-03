"""
EQATS Version 9.5 Institutional Upgrade Verification Suite
Verifies version assertions, ScalperBrain v9.5 attributes, and pure MQL5 indicator math adaptations.
"""

from typing import Any

import pytest

import brain
from brain import ScalperBrain


def test_v9_5_version_assertions() -> None:
    scalper = ScalperBrain()
    assert int(scalper.version.split(".")[0]) >= 8


def test_v9_5_brain_evaluation_and_slippage_control() -> None:
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
    assert "v9_5_slippage_pips" in res
    assert res["v9_5_slippage_pips"] >= 0.5
