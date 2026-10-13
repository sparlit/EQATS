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


"""IC computation — Spearman information coefficient, Newey-West t-stat, and decay.

All IC metrics are derived from the output of ``align_signal_to_returns`` in
``eval/alignment.py``.  This module never touches raw prices or returns directly.
"""


import warnings

import numpy as np
import pandas as pd
import scipy.stats
import statsmodels.api as sm

# Newey-West lag for heteroscedasticity/autocorrelation-consistent standard errors
NEWEY_WEST_LAG: int = 5

# Evaluation horizons (trading days)
DEFAULT_HORIZONS: list[int] = [1, 2, 3, 5, 10, 21]


# ---------------------------------------------------------------------------
# Per-date IC
# ---------------------------------------------------------------------------


def compute_ic_series(aligned: pd.DataFrame) -> pd.Series:
    """Compute cross-sectional Spearman rank IC per date.

    Parameters
    ----------
    aligned:
        DataFrame from ``align_signal_to_returns``.
        Columns: ``signal``, ``fwd_return``. MultiIndex ``(date, symbol)``.

    Returns
    -------
    pd.Series
        IC per date (DatetimeIndex).  Values in [-1, 1].
    """

    def _spearman(g: pd.DataFrame) -> float:
        if len(g) < 3:
            return float("nan")
        rho, _ = scipy.stats.spearmanr(g["signal"], g["fwd_return"])
        return float(rho)

    return aligned.groupby(level="date").apply(_spearman).rename("IC")


# ---------------------------------------------------------------------------
# IC statistics
# ---------------------------------------------------------------------------


def compute_ic_stats(ic_series: pd.Series) -> dict[str, float]:
    """Compute summary statistics for an IC time series.

    Parameters
    ----------
    ic_series:
        Daily IC values from ``compute_ic_series``.

    Returns
    -------
    dict with keys:
        ``ic_mean``, ``ic_std``, ``ic_tstat``, ``ir``
    where ``ir`` is the Information Ratio (IC mean / IC std, annualised).
    """
    ic_clean = ic_series.dropna()
    n = len(ic_clean)

    if n < 5:
        return {
            "ic_mean": float("nan"),
            "ic_std": float("nan"),
            "ic_tstat": float("nan"),
            "ir": float("nan"),
        }

    ic_mean = float(ic_clean.mean())
    ic_std = float(ic_clean.std(ddof=1))

    # Newey-West heteroscedasticity and autocorrelation consistent (HAC) t-stat
    # Regress IC on a constant, use HAC SE for the coefficient t-stat
    x_const = sm.add_constant(np.ones(n))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sm.OLS(ic_clean.values, x_const).fit()
        hac = model.get_robustcov_results(cov_type="HAC", maxlags=NEWEY_WEST_LAG)
    ic_tstat = float(hac.tvalues[0])  # t-stat for the intercept (= IC mean)

    # Information Ratio: annualised = (mean / std) * sqrt(252)
    ir = (ic_mean / ic_std) * np.sqrt(252) if ic_std > 0 else float("nan")

    return {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "ic_tstat": ic_tstat,
        "ir": ir,
    }


# ---------------------------------------------------------------------------
# IC decay
# ---------------------------------------------------------------------------


def compute_ic_decay(
    signal: pd.Series,
    panel: pd.DataFrame,
    horizons: list[int] | None = None,
) -> pd.DataFrame:
    """Compute mean IC for multiple forward horizons.

    Parameters
    ----------
    signal:
        Preprocessed signal series, MultiIndex ``(date, symbol)``.
    panel:
        Tidy panel with ``adj_close``.
    horizons:
        List of horizons in trading days.  Defaults to ``DEFAULT_HORIZONS``.

    Returns
    -------
    pd.DataFrame
        Columns: ``horizon``, ``ic_mean``, ``ic_std``, ``ic_tstat``.
    """
    from nse_alpha.eval.alignment import align_signal_to_returns

    if horizons is None:
        horizons = DEFAULT_HORIZONS

    rows: list[dict[str, float]] = []
    for h in horizons:
        aligned = align_signal_to_returns(signal, panel, horizon=h)
        ic_series = compute_ic_series(aligned)
        stats = compute_ic_stats(ic_series)
        rows.append({"horizon": float(h), **stats})

    return pd.DataFrame(rows)


def fit_ic_halflife(ic_decay: pd.DataFrame) -> float:
    """Fit an exponential decay model to the IC-vs-horizon curve.

    Model: ``IC(h) = IC(1) * exp(-lambda * h)``
    Half-life: ``t_{1/2} = ln(2) / lambda``

    Parameters
    ----------
    ic_decay:
        DataFrame from ``compute_ic_decay`` with columns
        ``horizon`` and ``ic_mean``.

    Returns
    -------
    float
        Estimated half-life in trading days.
        Returns ``float("nan")`` if fit fails or IC is not monotonically decaying.
    """
    import scipy.optimize

    horizons = ic_decay["horizon"].values
    ic_means = ic_decay["ic_mean"].abs().values  # use absolute IC (decay is absolute)

    if np.any(np.isnan(ic_means)) or ic_means[0] == 0:
        return float("nan")

    ic_norm = ic_means / ic_means[0]  # normalise to 1 at h=1

    def _exp_decay(h: np.ndarray, lam: float) -> np.ndarray:
        return np.exp(-lam * h)  # type: ignore[no-any-return]

    try:
        popt, _ = scipy.optimize.curve_fit(
            _exp_decay, horizons, ic_norm, p0=[0.1], bounds=(0, np.inf)
        )
        lam = popt[0]
        if lam <= 0:
            return float("nan")
        return float(np.log(2) / lam)
    except (RuntimeError, ValueError):
        return float("nan")
