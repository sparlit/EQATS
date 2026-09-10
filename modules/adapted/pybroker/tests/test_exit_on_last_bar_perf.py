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


"""Regression tests for exit_on_last_bar preprocessing correctness.

Ensures that the groupby-based implementation produces identical exit_dates
to the original per-symbol boolean-indexing implementation.
"""

import numpy as np
import pandas as pd
from pybroker.common import DataCol


def _reference_exit_dates(df: pd.DataFrame, executions):
    """Original O(E*S*N) implementation, kept as the ground truth."""
    exit_dates = {}
    for exec in executions:
        for sym in exec.symbols:
            sym_dates = df[df[DataCol.SYMBOL.value] == sym][DataCol.DATE.value].values
            if len(sym_dates):
                exit_dates[sym] = sym_dates.max()
    return exit_dates


def _new_exit_dates(df: pd.DataFrame, executions):
    """New O(N) groupby implementation."""
    exit_dates = {}
    exit_symbols = set()
    for exec in executions:
        exit_symbols.update(exec.symbols)
    if exit_symbols and not df.empty:
        sym_col = DataCol.SYMBOL.value
        date_col = DataCol.DATE.value
        mask = df[sym_col].isin(exit_symbols)
        grouped = df.loc[mask].groupby(sym_col, sort=False)[date_col].max()
        exit_dates = {sym: np.datetime64(date) for sym, date in grouped.items()}
    return exit_dates


class _FakeExecution:
    def __init__(self, symbols):
        self.symbols = frozenset(symbols)


def _make_df(symbols, n_bars_per_sym=20):
    dates = pd.date_range("2023-01-01", periods=n_bars_per_sym, freq="D")
    rows = []
    for sym in symbols:
        for d in dates:
            rows.append({DataCol.SYMBOL.value: sym, DataCol.DATE.value: d})
    return pd.DataFrame(rows)


def test_single_execution_single_symbol():
    df = _make_df(["AAPL"])
    execs = [_FakeExecution(["AAPL"])]
    assert _new_exit_dates(df, execs) == _reference_exit_dates(df, execs)


def test_multiple_executions_overlapping_symbols():
    df = _make_df(["AAPL", "MSFT", "GOOG"])
    execs = [
        _FakeExecution(["AAPL", "MSFT"]),
        _FakeExecution(["MSFT", "GOOG"]),
    ]
    assert _new_exit_dates(df, execs) == _reference_exit_dates(df, execs)


def test_empty_dataframe():
    df = pd.DataFrame({DataCol.SYMBOL.value: [], DataCol.DATE.value: []})
    execs = [_FakeExecution(["AAPL"])]
    assert _new_exit_dates(df, execs) == {}


def test_no_executions():
    df = _make_df(["AAPL"])
    assert _new_exit_dates(df, []) == {}


def test_symbol_not_in_df():
    df = _make_df(["AAPL"])
    execs = [_FakeExecution(["AAPL", "UNKNOWN"])]
    new = _new_exit_dates(df, execs)
    ref = _reference_exit_dates(df, execs)
    assert new == ref
    assert "UNKNOWN" not in new


def test_returns_numpy_datetime64():
    df = _make_df(["AAPL"])
    execs = [_FakeExecution(["AAPL"])]
    result = _new_exit_dates(df, execs)
    assert isinstance(result["AAPL"], np.datetime64)
