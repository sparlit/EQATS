import numpy as np
import pandas as pd
from app.utils.market_data import extract_ticker_df


def make_batch_df(tickers, n_rows=5):
    """Simulate yfinance batch download: MultiIndex (ticker, field)."""
    fields = ["Close", "High", "Low", "Open", "Volume"]
    arrays = [
        [t for t in tickers for _ in fields],
        fields * len(tickers),
    ]
    columns = pd.MultiIndex.from_arrays(arrays)
    data = np.ones((n_rows, len(tickers) * len(fields))) * 100.0
    return pd.DataFrame(data, columns=columns)


def make_single_ticker_multiindex_df(ticker, n_rows=5):
    """Simulate yfinance single-ticker download with (field, ticker) MultiIndex."""
    fields = ["Close", "High", "Low", "Open", "Volume"]
    arrays = [fields, [ticker] * len(fields)]
    columns = pd.MultiIndex.from_arrays(arrays)
    data = np.ones((n_rows, len(fields))) * 100.0
    return pd.DataFrame(data, columns=columns)


# ── Batch MultiIndex (ticker at level 0) ─────────────────────────────────────

def test_extract_known_ticker_from_batch():
    raw = make_batch_df(["TITAN.NS", "RELIANCE.NS"])
    result = extract_ticker_df(raw, "TITAN.NS")
    assert result is not None
    assert "Close" in result.columns
    assert not isinstance(result.columns, pd.MultiIndex)


def test_extract_missing_ticker_returns_none():
    raw = make_batch_df(["TITAN.NS", "RELIANCE.NS"])
    result = extract_ticker_df(raw, "INFY.NS")
    assert result is None


def test_extracted_df_has_all_fields():
    raw = make_batch_df(["TITAN.NS"])
    result = extract_ticker_df(raw, "TITAN.NS")
    for field in ["Close", "High", "Low", "Open", "Volume"]:
        assert field in result.columns


# ── Single-ticker MultiIndex (field at level 0) ───────────────────────────────

def test_single_ticker_multiindex_flattened():
    raw = make_single_ticker_multiindex_df("TITAN.NS")
    result = extract_ticker_df(raw, "TITAN.NS")
    assert result is not None
    assert "Close" in result.columns
    assert not isinstance(result.columns, pd.MultiIndex)


def test_single_ticker_multiindex_unknown_ticker_returns_none():
    raw = make_single_ticker_multiindex_df("TITAN.NS")
    result = extract_ticker_df(raw, "DIFFERENT.NS")
    assert result is None


def make_new_batch_df(tickers, n_rows=5):
    """Simulate new yfinance batch format: MultiIndex (field, ticker)."""
    fields = ["Close", "High", "Low", "Open", "Volume"]
    arrays = [
        fields * len(tickers),
        [t for t in tickers for _ in fields],
    ]
    columns = pd.MultiIndex.from_arrays(arrays)
    data = np.ones((n_rows, len(tickers) * len(fields))) * 100.0
    return pd.DataFrame(data, columns=columns)


def test_new_format_batch_extracts_correct_ticker():
    raw = make_new_batch_df(["TITAN.NS", "RELIANCE.NS"])
    result = extract_ticker_df(raw, "TITAN.NS")
    assert result is not None
    assert not isinstance(result.columns, pd.MultiIndex)
    for field in ["Close", "High", "Low", "Open", "Volume"]:
        assert field in result.columns


def test_new_format_batch_missing_ticker_returns_none():
    raw = make_new_batch_df(["TITAN.NS", "RELIANCE.NS"])
    result = extract_ticker_df(raw, "INFY.NS")
    assert result is None


# ── Flat DataFrame (no MultiIndex) ───────────────────────────────────────────

def test_flat_df_returned_unchanged():
    df = pd.DataFrame({"Close": [100.0, 101.0], "Volume": [1000, 2000]})
    result = extract_ticker_df(df, "TITAN.NS")
    assert result is df


def test_flat_df_columns_intact():
    df = pd.DataFrame({"Close": [100.0], "Open": [99.0], "Volume": [5000]})
    result = extract_ticker_df(df, "ANY.NS")
    assert list(result.columns) == ["Close", "Open", "Volume"]
