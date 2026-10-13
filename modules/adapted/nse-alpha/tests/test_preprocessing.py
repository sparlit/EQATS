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


"""Hypothesis property-based tests for preprocessing functions.

Properties verified:
1. Winsorisation preserves rank order within each cross-section (monotone clip).
2. Cross-sectional z-scoring produces zero mean within each date.
3. Sector neutralisation residuals are orthogonal to sector dummies per date.
"""


import numpy as np
import pandas as pd
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from nse_alpha.eval.preprocessing import (
    cross_section_zscore,
    sector_neutralise,
    winsorise,
)

# ---------------------------------------------------------------------------
# Helpers to build MultiIndex Series for tests
# ---------------------------------------------------------------------------


def _make_two_date_series(vals_d1: list[float], vals_d2: list[float]) -> pd.Series:
    """Build a (date, symbol) indexed Series with two dates."""
    n = len(vals_d1)
    assert len(vals_d2) == n
    symbols = [f"S{i}" for i in range(n)]
    dates = ["2020-01-01", "2020-01-02"]
    index = pd.MultiIndex.from_tuples(
        [(d, s) for d in dates for s in symbols],
        names=["date", "symbol"],
    )
    values = vals_d1 + vals_d2
    return pd.Series(values, index=index, name="score", dtype=float)


# ---------------------------------------------------------------------------
# Property 1: Winsorisation preserves rank order
# ---------------------------------------------------------------------------


@given(
    st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=50,
    )
)
@settings(max_examples=100)
def test_winsorise_preserves_rank_order(vals: list[float]) -> None:
    """After winsorisation, rank order within each date is preserved."""
    assume(len(set(vals)) > 1)  # skip degenerate all-equal case (NaN rank_corr)
    series = _make_two_date_series(vals, vals[::-1])
    winsorised = winsorise(series)

    for date in series.index.get_level_values("date").unique():
        orig_slice = series.xs(date, level="date")
        wins_slice = winsorised.xs(date, level="date")

        orig_rank = orig_slice.rank()
        wins_rank = wins_slice.rank()

        # Rank correlation must be 1.0 (ties allowed)
        rank_corr = orig_rank.corr(wins_rank)
        if float(orig_rank.std()) == 0.0:  # all-same ranks, skip
            continue
        assert rank_corr >= 0.9999, (
            f"Winsorisation broke rank order for date={date}: rank_corr={rank_corr}"
        )


# ---------------------------------------------------------------------------
# Property 2: Z-score produces zero cross-sectional mean
# ---------------------------------------------------------------------------


@given(
    st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=50,
    )
)
@settings(max_examples=100)
def test_zscore_produces_zero_mean(vals: list[float]) -> None:
    """Cross-sectional z-score produces zero mean per date."""
    assume(len(set(vals)) > 1)  # avoid degenerate all-equal case

    series = _make_two_date_series(vals, vals[::-1])
    zscored = cross_section_zscore(series)

    for date in zscored.index.get_level_values("date").unique():
        z_slice = zscored.xs(date, level="date").dropna()
        if len(z_slice) > 0:
            mean = float(z_slice.mean())
            assert abs(mean) < 1e-10, f"Z-score mean={mean:.2e} is not zero for date={date}"


# ---------------------------------------------------------------------------
# Property 3: Sector neutralisation residuals orthogonal to sector factor
# ---------------------------------------------------------------------------


def test_sector_neutralise_residuals_orthogonal() -> None:
    """Sector-neutralised residuals have zero within-sector mean per date."""
    rng = np.random.default_rng(0)
    n = 40
    symbols = [f"S{i}" for i in range(n)]
    sectors = ["Tech"] * 10 + ["Finance"] * 10 + ["Energy"] * 10 + ["Pharma"] * 10
    sector_map = dict(zip(symbols, sectors, strict=False))

    dates = ["2020-01-01", "2020-01-02"]
    index = pd.MultiIndex.from_tuples(
        [(d, s) for d in dates for s in symbols],
        names=["date", "symbol"],
    )
    values = rng.standard_normal(len(dates) * n)
    scores = pd.Series(values, index=index, name="score")

    neutralised = sector_neutralise(scores, sector_map)

    for date in dates:
        n_slice = neutralised.xs(date, level="date")
        for sector in set(sectors):
            sector_syms = [s for s, sec in sector_map.items() if sec == sector]
            sector_vals = n_slice[sector_syms].dropna()
            if len(sector_vals) > 0:
                mean = float(sector_vals.mean())
                assert abs(mean) < 1e-10, (
                    f"Sector '{sector}' residual mean={mean:.2e} non-zero for date={date}"
                )


# ---------------------------------------------------------------------------
# Additional edge case: Z-score of constant series produces NaN (not error)
# ---------------------------------------------------------------------------


def test_zscore_constant_series_returns_nan() -> None:
    """Z-scoring a constant cross-section returns NaN, not an error."""
    n = 5
    symbols = [f"S{i}" for i in range(n)]
    index = pd.MultiIndex.from_tuples(
        [("2020-01-01", s) for s in symbols], names=["date", "symbol"]
    )
    # All same value → std = 0
    series = pd.Series([1.0] * n, index=index)
    result = cross_section_zscore(series)
    assert result.isna().all(), "Constant series should produce all-NaN z-scores"
