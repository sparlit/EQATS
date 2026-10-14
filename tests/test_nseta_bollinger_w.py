import datetime
import sys
import types
import numpy as np
import pandas as pd
import pytest

# Ensure nseta path is available for imports within modules/adapted/nseta
from pathlib import Path
nseta_path = str(Path(__file__).resolve().parent.parent / "modules" / "adapted" / "nseta")
if nseta_path not in sys.path:
    sys.path.insert(0, nseta_path)

# Mock optional/external dependencies if not present in the runtime virtualenv
if "pytz" not in sys.modules:
    pytz_mock = types.ModuleType("pytz")
    pytz_mock.__version__ = "2024.1"
    pytz_mock.UTC = datetime.timezone.utc
    pytz_mock.timezone = lambda tz: datetime.timezone.utc
    sys.modules["pytz"] = pytz_mock

if "matplotlib" not in sys.modules:
    mpl_mock = types.ModuleType("matplotlib")
    mpl_dates_mock = types.ModuleType("matplotlib.dates")
    mpl_plt_mock = types.ModuleType("matplotlib.pyplot")
    sys.modules["matplotlib"] = mpl_mock
    sys.modules["matplotlib.dates"] = mpl_dates_mock
    sys.modules["matplotlib.pyplot"] = mpl_plt_mock

if "termcolor" not in sys.modules:
    termcolor_mock = types.ModuleType("termcolor")
    termcolor_mock.colored = lambda text, *args, **kwargs: text
    sys.modules["termcolor"] = termcolor_mock

from modules.adapted.nseta.nseta.strategy.bollingerbandsBottomWStrategy import (
    bollingerbandsBottomWStrategy,
    round_to_ist_tick,
)


def test_round_to_ist_tick():
    assert round_to_ist_tick(100.02) == 100.0
    assert round_to_ist_tick(100.03) == 100.05
    assert round_to_ist_tick(100.08) == 100.10
    assert round_to_ist_tick(-5.0) == 0.0


def test_bollinger_bands_calculation():
    strategy = bollingerbandsBottomWStrategy()
    dates = pd.date_range("2024-01-01", periods=30)
    prices = np.linspace(100, 110, 30)
    df = pd.DataFrame({"Date": dates, "Symbol": "TEST", "close": prices})

    bb_df = strategy.bollinger_bands(df)
    assert "mid_band" in bb_df.columns
    assert "upper_band" in bb_df.columns
    assert "lower_band" in bb_df.columns
    assert len(bb_df) == 11  # 30 - 20 + 1 rolling window valid entries


def test_signal_generation_basic():
    strategy = bollingerbandsBottomWStrategy()
    dates = pd.date_range("2024-01-01", periods=80)
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(80))
    df = pd.DataFrame({"Date": dates, "Symbol": "RELIANCE", "close": prices})

    signals = strategy.signal_generation(df)
    assert "bb_signal" in signals.columns
    assert "bb_position" in signals.columns
    assert "coordinates" in signals.columns
    # signal_generation calls bollinger_bands(df) which drops NaN rows from 20-period rolling window
    assert len(signals) == 61
