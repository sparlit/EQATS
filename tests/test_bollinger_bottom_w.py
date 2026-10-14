import sys
from pathlib import Path

# Ensure module path is available for imports
nseta_path = Path(__file__).resolve().parent.parent / "modules" / "adapted" / "nseta"
if str(nseta_path) not in sys.path:
    sys.path.insert(0, str(nseta_path))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from nseta.strategy.bollingerbandsBottomWStrategy import (  # noqa: E402
    bollingerbandsBottomWStrategy,
)


def test_bollinger_bands_calculation():
    strategy = bollingerbandsBottomWStrategy()
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
    df = pd.DataFrame(
        {
            "Date": dates.strftime("%Y-%m-%d %H:%M:%S"),
            "Symbol": "TESTSTOCK",
            "close": np.linspace(100, 150, 100),
        }
    )
    res = strategy.bollinger_bands(df)
    assert "std" in res.columns
    assert "mid_band" in res.columns
    assert "upper_band" in res.columns
    assert "lower_band" in res.columns
    assert len(res) == 81  # min_periods=20 drops first 19 rows


def test_signal_generation_runs_without_errors():
    strategy = bollingerbandsBottomWStrategy()
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=120, freq="D")
    prices = 100 + np.cumsum(np.random.randn(120))
    df = pd.DataFrame(
        {
            "Date": dates.strftime("%Y-%m-%d %H:%M:%S"),
            "Symbol": "TESTSTOCK",
            "close": prices,
        }
    )
    signals = strategy.signal_generation(df)
    assert "bb_signal" in signals.columns
    assert "bb_position" in signals.columns
    assert "coordinates" in signals.columns
    assert len(signals) > 0


def test_calculate_roi_insufficient_signals(capsys):
    strategy = bollingerbandsBottomWStrategy()
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
    df = pd.DataFrame(
        {
            "Date": dates.strftime("%Y-%m-%d %H:%M:%S"),
            "Symbol": "TESTSTOCK",
            "close": np.linspace(100, 110, 100),
            "bb_signal": np.zeros(100, dtype=int),
            "bb_position": np.zeros(100, dtype=int),
        }
    )
    result = strategy.calculate_roi(df, "TESTSTOCK")
    assert result is False
    captured = capsys.readouterr()
    assert "Not enough data yet" in captured.out
