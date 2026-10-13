from __future__ import annotations

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


"""Tests for the yfinance data ingestion and caching layer."""


import numpy as np
import pandas as pd
import pytest
from nse_alpha.data.cache import (
    get_cached_range,
    load_symbol,
    save_to_cache,
)
from nse_alpha.data.ingest import (
    _extract_symbol_slice,
    _normalise_single,
)
from nse_alpha.data.panel import build_panel


def test_normalise_single_standard_columns() -> None:
    """Test column renaming and turnover calculation."""
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    raw = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [105.0, 106.0, 107.0, 108.0, 109.0],
            "Low": [95.0, 96.0, 97.0, 98.0, 99.0],
            "Close": [102.0, 103.0, 104.0, 105.0, 106.0],
            "Adj Close": [101.5, 102.5, 103.5, 104.5, 105.5],
            "Volume": [1000, 2000, 1500, 3000, 2500],
        },
        index=dates,
    )

    norm = _normalise_single(raw, "TEST.NS")
    assert norm is not None
    assert list(norm.columns) == [
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "turnover_value",
    ]
    assert np.allclose(norm["turnover_value"], norm["close"] * norm["volume"])
    assert norm.index.name == "date"


def test_normalise_single_fallback_adj_close() -> None:
    """When Adj Close is missing, it should fallback to Close."""
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    raw = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [95.0, 96.0, 97.0],
            "Close": [102.0, 103.0, 104.0],
            "Volume": [1000, 2000, 1500],
        },
        index=dates,
    )

    norm = _normalise_single(raw, "TEST.NS")
    assert norm is not None
    assert "adj_close" in norm.columns
    assert np.allclose(norm["adj_close"], norm["close"])


def test_extract_symbol_slice_multiindex() -> None:
    """Test extracting symbol slice from yfinance MultiIndex output."""
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    cols = pd.MultiIndex.from_tuples(
        [
            ("RELIANCE.NS", "Open"),
            ("RELIANCE.NS", "Close"),
            ("TCS.NS", "Open"),
            ("TCS.NS", "Close"),
        ]
    )
    raw = pd.DataFrame(
        [
            [100, 102, 200, 202],
            [101, 103, 201, 203],
            [102, 104, 202, 204],
        ],
        index=dates,
        columns=cols,
    )

    slice_rel = _extract_symbol_slice(raw, "RELIANCE.NS", ["RELIANCE.NS", "TCS.NS"])
    assert slice_rel is not None
    assert "Open" in slice_rel.columns or ("RELIANCE.NS", "Open") in slice_rel.columns


def test_cache_and_panel_offline(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test caching, offline loading, and panel construction."""
    monkeypatch.setenv("NSE_ALPHA_OFFLINE", "1")

    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 10),
            "high": np.linspace(105, 115, 10),
            "low": np.linspace(95, 105, 10),
            "close": np.linspace(102, 112, 10),
            "adj_close": np.linspace(102, 112, 10),
            "volume": [1000.0] * 10,
            "turnover_value": np.linspace(102000, 112000, 10),
        },
        index=dates,
    )

    save_to_cache("TEST_OFFLINE.NS", df, "2024-01-01", "2024-01-10")

    loaded = load_symbol("TEST_OFFLINE.NS")
    assert loaded is not None
    assert len(loaded) == 10

    cached_range = get_cached_range("TEST_OFFLINE.NS")
    assert cached_range is not None
    assert cached_range["start"] == "2024-01-01"

    panel = build_panel(["TEST_OFFLINE.NS"], "2024-01-01", "2024-01-05", download=False)
    assert len(panel) == 5
    assert isinstance(panel.index, pd.MultiIndex)
