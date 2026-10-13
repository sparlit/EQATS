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


"""Signal preprocessing — winsorisation, z-scoring, and neutralisation.

These three steps are applied uniformly to every signal before IC computation:
    1. Winsorise cross-sectionally at 1st / 99th percentile, per date.
    2. Cross-sectional z-score (zero mean, unit std), per date.
    3. Optional neutralisation: sector or size (controlled by config).

All operations preserve the MultiIndex ``(date, symbol)`` structure and
operate independently within each date to avoid any cross-date leakage.
"""


import numpy as np
import pandas as pd
import statsmodels.api as sm

# ---------------------------------------------------------------------------
# 1. Winsorisation
# ---------------------------------------------------------------------------


def winsorise(
    scores: pd.Series,
    lower: float = 0.01,
    upper: float = 0.99,
) -> pd.Series:
    """Clip signal scores at the *lower* and *upper* cross-sectional percentiles.

    Applied independently per date to avoid any temporal contamination.

    Parameters
    ----------
    scores:
        Signal series with MultiIndex ``(date, symbol)``.
    lower, upper:
        Percentile bounds in [0, 1].

    Returns
    -------
    pd.Series
        Winsorised scores with the same index.

    Property: rank order within each date is preserved (monotone clipping).
    """

    def _clip_group(g: pd.Series) -> pd.Series:
        lo = g.quantile(lower)
        hi = g.quantile(upper)
        return g.clip(lo, hi)

    return scores.groupby(level="date", group_keys=False).apply(_clip_group)


# ---------------------------------------------------------------------------
# 2. Cross-sectional z-score
# ---------------------------------------------------------------------------


def cross_section_zscore(scores: pd.Series) -> pd.Series:
    """Standardise scores to zero cross-sectional mean and unit std, per date.

    Dates where std == 0 (all values identical) are dropped (result is NaN
    for that date, which is then excluded in alignment).

    Parameters
    ----------
    scores:
        Signal series with MultiIndex ``(date, symbol)``.

    Returns
    -------
    pd.Series
        Z-scored scores.  Cross-sectional mean ≈ 0, std ≈ 1. per date.
    """

    def _zscore_group(g: pd.Series) -> pd.Series:
        mu = g.mean()
        sigma = g.std(ddof=1)
        if sigma == 0 or np.isnan(sigma):
            return pd.Series(np.nan, index=g.index)
        return (g - mu) / sigma

    return scores.groupby(level="date", group_keys=False).apply(_zscore_group)


# ---------------------------------------------------------------------------
# 3. Neutralisation
# ---------------------------------------------------------------------------


def sector_neutralise(
    scores: pd.Series,
    sector_map: dict[str, str],
) -> pd.Series:
    """Remove cross-sectional sector mean from scores (demean within sector).

    Parameters
    ----------
    scores:
        Z-scored signal series with MultiIndex ``(date, symbol)``.
    sector_map:
        ``{symbol: sector}`` mapping.

    Returns
    -------
    pd.Series
        Scores with sector mean removed.  Residuals are orthogonal to sector
        dummies within each date.

    Notes
    -----
    Symbols not found in *sector_map* are assigned to ``"Unknown"`` sector.
    """
    symbols = scores.index.get_level_values("symbol")
    sector_labels = pd.Series(
        [sector_map.get(s, "Unknown") for s in symbols],
        index=scores.index,
        name="sector",
    )

    def _neutralise_group(g: pd.Series) -> pd.Series:
        g_sectors = sector_labels.loc[g.index]
        group_means = g.groupby(g_sectors.values).transform("mean")
        return g - group_means

    return scores.groupby(level="date", group_keys=False).apply(_neutralise_group)


def size_neutralise(
    scores: pd.Series,
    log_adv: pd.Series,
) -> pd.Series:
    """Remove cross-sectional size (log ADV) exposure via OLS regression.

    Parameters
    ----------
    scores:
        Z-scored signal series with MultiIndex ``(date, symbol)``.
    log_adv:
        Log of 20-day average daily value traded, same MultiIndex.

    Returns
    -------
    pd.Series
        OLS residuals after regressing ``scores`` on ``log_adv``, per date.
        Residuals are orthogonal to ``log_adv`` within numerical tolerance.
    """

    def _residualise_group(group_df: pd.DataFrame) -> pd.Series:
        y = group_df["scores"]
        x = sm.add_constant(group_df["log_adv"])
        valid = y.notna() & group_df["log_adv"].notna()
        if valid.sum() < 3:  # not enough to fit
            return pd.Series(np.nan, index=y.index)
        try:
            model = sm.OLS(y[valid], x[valid]).fit()
            resid = pd.Series(np.nan, index=y.index)
            resid[valid] = model.resid
            return resid
        except Exception:
            return pd.Series(np.nan, index=y.index)

    combined = pd.DataFrame({"scores": scores, "log_adv": log_adv})
    result = combined.groupby(level="date", group_keys=False).apply(_residualise_group)
    return result["scores"] if isinstance(result, pd.DataFrame) else result


# ---------------------------------------------------------------------------
# 4. Full preprocessing pipeline
# ---------------------------------------------------------------------------


def preprocess(
    scores: pd.Series,
    *,
    sector_map: dict[str, str] | None = None,
    log_adv: pd.Series | None = None,
    winsorise_bounds: tuple[float, float] = (0.01, 0.99),
) -> pd.Series:
    """Apply the standard 3-step preprocessing pipeline.

    Steps:
    1. Winsorise at *winsorise_bounds* cross-sectionally per date.
    2. Cross-sectional z-score per date.
    3. Sector neutralise if *sector_map* is provided.
    4. Size neutralise if *log_adv* is provided.

    Parameters
    ----------
    scores:
        Raw signal scores, MultiIndex ``(date, symbol)``.
    sector_map:
        Optional ``{symbol: sector}`` for sector neutralisation.
    log_adv:
        Optional log-ADV series for size neutralisation.
    winsorise_bounds:
        ``(lower, upper)`` percentile clip bounds.

    Returns
    -------
    pd.Series
        Preprocessed signal scores.
    """
    out = winsorise(scores, *winsorise_bounds)
    out = cross_section_zscore(out)
    if sector_map is not None:
        out = sector_neutralise(out, sector_map)
    if log_adv is not None:
        out = size_neutralise(out, log_adv)
    return out
