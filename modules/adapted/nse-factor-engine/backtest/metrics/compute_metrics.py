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


"""
Backtest Metrics — Phase 5

Computes all metrics per METHODOLOGY.md §6.8 for:
    - 25 strategy cells
    - benchmark (Nifty 500)

Input  : backtest_weekly_returns_{DDMMYYYY}.parquet
Output : backtest_results_{DDMMYYYY}.parquet (25 rows × summary metrics)
"""

import numpy as np
import pandas as pd

RF = 0.07
YEARS = 10
INITIAL = 10_000_000.0


def _cagr(cum_return: float) -> float:
    """(1 + cum_return)^(1/10) - 1"""
    return (1 + cum_return) ** (1 / YEARS) - 1


def _sharpe(weekly_rets: pd.Series) -> float:
    mean = weekly_rets.mean()
    std = weekly_rets.std()
    if std == 0 or pd.isna(std):
        return np.nan
    return (mean * 52 - RF) / (std * np.sqrt(52))


def _sortino(weekly_rets: pd.Series) -> float:
    mean = weekly_rets.mean()
    neg_rets = weekly_rets[weekly_rets < 0]
    if len(neg_rets) < 2:
        return np.nan
    down_std = neg_rets.std()
    if down_std == 0 or pd.isna(down_std):
        return np.nan
    return (mean * 52 - RF) / (down_std * np.sqrt(52))


def _max_dd(weekly_rets: pd.Series) -> float:
    """Largest peak-to-trough in cumulative value series."""
    cum = (1 + weekly_rets).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return dd.min()  # negative number


def _dd_recovery(weekly_rets: pd.Series) -> int:
    """Weeks from max DD trough to recovery of prior peak."""
    cum = (1 + weekly_rets).cumprod().reset_index(drop=True)
    peak = cum.cummax()
    dd = (cum - peak) / peak
    trough_pos = int(dd.argmin())  # positional — safe after reset_index
    peak_val = peak.iloc[trough_pos]
    post_trough = cum.iloc[trough_pos + 1 :]
    recovered = post_trough[post_trough >= peak_val]
    if len(recovered) == 0:
        return len(post_trough)
    return int(recovered.index[0] - trough_pos)


def _deflated_sharpe(sharpe: float, n_strategies: int, n_obs: int) -> tuple:
    """
    Deflated Sharpe Ratio — flag only per METHODOLOGY.md §6.8.

    Uses Bailey & Lopez de Prado (2012) approximation:
        SR_threshold = sqrt(log(n_strategies) / 2)
    Annualised Sharpe must exceed this threshold to be flagged significant.

    This is a conservative multiple-testing adjustment:
    - 25 strategies → threshold ≈ 1.2686
    - Sharpe must be materially positive to pass
    """
    if pd.isna(sharpe) or n_obs < 2:
        return np.nan, False

    threshold = np.sqrt(np.log(n_strategies) / 2)
    deflated = round(sharpe - threshold, 4)
    significant = bool(sharpe > threshold)
    return deflated, significant


def norm_ppf(p: float) -> float:
    """Percent point function of standard normal — scipy-free approximation."""
    # Beasley-Springer-Moro algorithm approximation
    from math import log, sqrt

    if p <= 0 or p >= 1:
        return float("inf") if p >= 1 else float("-inf")
    a = [
        0,
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        0,
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = sqrt(-2 * log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[1] * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * r + a[6])
            * q
            / (((((b[1] * r + b[2]) * r + b[3]) * r + b[4]) * r + b[5]) * r + 1)
        )
    q = sqrt(-2 * log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def _dd_buckets(weekly_rets: pd.Series) -> dict:
    return {
        "weeks_positive": int((weekly_rets >= 0).sum()),
        "weeks_dd_0_5": int(((weekly_rets < 0) & (weekly_rets >= -0.05)).sum()),
        "weeks_dd_5_10": int(((weekly_rets < -0.05) & (weekly_rets >= -0.10)).sum()),
        "weeks_dd_10_20": int(((weekly_rets < -0.10) & (weekly_rets >= -0.20)).sum()),
        "weeks_dd_gt20": int((weekly_rets < -0.20).sum()),
    }


def compute_cell_metrics(
    cell_id: str,
    weekly_rets: pd.Series,
    bench_cagr: float,
    n_strategies: int = 25,
) -> dict:
    """Compute all metrics for one cell."""
    rets = weekly_rets.dropna()
    # skip week 1 (return = 0 by construction)
    rets = rets.iloc[1:]

    cum_ret = (1 + rets).prod() - 1
    cagr = _cagr(cum_ret)
    sharpe = _sharpe(rets)
    sortino = _sortino(rets)
    max_dd = _max_dd(rets)
    dd_rec = _dd_recovery(rets)
    defl, sig = _deflated_sharpe(sharpe, n_strategies, len(rets))
    buckets = _dd_buckets(rets)

    gate_id, score_id = cell_id.split("_")

    return {
        "cell_id": cell_id,
        "gate_variant": gate_id,
        "score_variant": score_id,
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_dd": round(max_dd, 4),
        "dd_recovery_weeks": int(dd_rec),
        "deflated_sharpe_margin": defl,
        "sharpe_significant": sig,
        "alpha": round(cagr - bench_cagr, 4),
        "benchmark_cagr": round(bench_cagr, 4),
        "total_weeks": len(rets),
        "initial_capital": INITIAL,
        "rf_rate": RF,
        **buckets,
    }


def compute_benchmark_metrics(bench_rets: pd.Series) -> dict:
    """Compute metrics for benchmark — same formulas, no alpha."""
    rets = bench_rets.dropna().iloc[1:]
    cum_ret = (1 + rets).prod() - 1
    return {
        "cell_id": "BENCHMARK",
        "cagr": round(_cagr(cum_ret), 4),
        "sharpe": round(_sharpe(rets), 4),
        "sortino": round(_sortino(rets), 4),
        "max_dd": round(_max_dd(rets), 4),
        "dd_recovery_weeks": int(_dd_recovery(rets)),
        **_dd_buckets(rets),
    }


def run(weekly_returns_path: str) -> pd.DataFrame:
    """
    Main entry point.
    weekly_returns_path : path to backtest_weekly_returns_{DDMMYYYY}.parquet
    Returns             : results DataFrame (25 rows)
    """
    df = pd.read_parquet(weekly_returns_path)

    # benchmark CAGR
    bench_rets = df["benchmark"].dropna().iloc[1:]
    bench_cum = (1 + bench_rets).prod() - 1
    bench_cagr = _cagr(bench_cum)

    cell_cols = [c for c in df.columns if c not in ["friday_date", "benchmark"]]
    rows = []
    for cell_id in cell_cols:
        metrics = compute_cell_metrics(cell_id, df[cell_id], bench_cagr)
        rows.append(metrics)
        print(
            f"  {cell_id}: CAGR={metrics['cagr']:.2%} Sharpe={metrics['sharpe']:.2f} "
            f"MaxDD={metrics['max_dd']:.2%} Alpha={metrics['alpha']:.2%}"
        )

    results = pd.DataFrame(rows)
    return results, compute_benchmark_metrics(df["benchmark"])
