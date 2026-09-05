"""
risk_metrics.py — Complete Risk Metrics Suite
==============================================

Computes the full set of required risk and performance metrics from
simulated price path arrays.

All functions accept NumPy arrays and return plain Python dicts or
NumPy arrays so they are easily serialisable for reporting.

Metrics covered
---------------
Terminal distribution  : mean, median, std, skew, kurtosis
Price forecast         : 5th/25th/50th/75th/95th percentile prices
Probabilities          : P(S_T > S0), P(return > target), P(loss)
                         Threshold breach probs at ±5/10/20%
VaR / CVaR             : at 95% and 99% confidence
Drawdown               : per-path max drawdown array, avg, worst
                         P(drawdown > threshold)
Volatility             : realised vs. simulated (annualised)
Sharpe ratio           : distribution across paths
Sortino ratio          : downside deviation-based
Confidence bands       : 5/25/50/75/95th percentile price paths over time
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR: int = 252


# ─── Public API ───────────────────────────────────────────────────────────────

def compute_all_metrics(
    paths: np.ndarray,
    params: Dict[str, float],
    processed_df: pd.DataFrame,
    cfg: dict,
    model_name: str = "GBM",
) -> Dict:
    """
    Compute the complete suite of risk and performance metrics.

    Parameters
    ----------
    paths : np.ndarray, shape (n_paths, n_steps + 1)
        Simulated price paths from any model.
    params : dict
        GBM parameters including ``S0``, ``sigma_annual``.
    processed_df : pd.DataFrame
        Processed historical data with ``log_return`` column.
    cfg : dict
        Full configuration dictionary.
    model_name : str
        Label for logging / report display.

    Returns
    -------
    dict
        Nested dictionary with all metrics grouped by category.
    """
    risk_cfg = cfg["risk"]
    S0: float = params["S0"]
    rf: float = risk_cfg["risk_free_rate"]
    target_ret: float = risk_cfg["target_return"]
    var_levels: List[float] = risk_cfg["var_levels"]
    dd_thresholds: List[float] = risk_cfg["drawdown_thresholds"]
    breach_pcts: List[float] = risk_cfg["price_breach_pcts"]
    n_steps = paths.shape[1] - 1

    terminal_prices = paths[:, -1]          # shape (n_paths,)
    terminal_returns = terminal_prices / S0 - 1.0

    logger.info("[%s] Computing risk metrics for %d paths × %d steps …",
                model_name, paths.shape[0], n_steps)

    metrics = {
        "model": model_name,
        "S0": S0,
        "n_paths": paths.shape[0],
        "n_steps": n_steps,
        "terminal": _terminal_stats(terminal_prices, terminal_returns),
        "forecast": _price_forecast(terminal_prices, S0),
        "probabilities": _probability_metrics(
            terminal_prices, terminal_returns, S0, target_ret, breach_pcts
        ),
        "var_cvar": _var_cvar(terminal_returns, var_levels),
        "drawdown": _drawdown_metrics(paths, dd_thresholds),
        "volatility": _volatility_comparison(paths, processed_df, n_steps),
        "sharpe_sortino": _sharpe_sortino(paths, S0, rf, n_steps),
        "confidence_bands": _confidence_bands(paths),
    }

    _log_key_metrics(metrics, model_name)
    return metrics


def build_comparison_table(all_metrics: Dict[str, Dict]) -> pd.DataFrame:
    """
    Build a side-by-side model comparison table.

    Parameters
    ----------
    all_metrics : dict
        Mapping of model_name → metrics dict (output of ``compute_all_metrics``).

    Returns
    -------
    pd.DataFrame
        Comparison table with models as columns.
    """
    rows = {}
    for model, m in all_metrics.items():
        t = m["terminal"]
        vc = m["var_cvar"]
        ss = m["sharpe_sortino"]
        dd = m["drawdown"]

        rows[model] = {
            "Mean Terminal Price": t["mean"],
            "Median Terminal Price": t["median"],
            "Std Dev": t["std"],
            "Skewness": t["skewness"],
            "Excess Kurtosis": t["kurtosis"],
            "VaR 95%": vc.get("var_0.95", np.nan),
            "VaR 99%": vc.get("var_0.99", np.nan),
            "CVaR 95%": vc.get("cvar_0.95", np.nan),
            "CVaR 99%": vc.get("cvar_0.99", np.nan),
            "Mean Sharpe": ss["mean_sharpe"],
            "Sortino": ss["sortino"],
            "Avg Max Drawdown": dd["avg_max_drawdown"],
            "Worst Drawdown": dd["worst_drawdown"],
        }

    return pd.DataFrame(rows).T


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _terminal_stats(terminal_prices: np.ndarray, terminal_returns: np.ndarray) -> Dict:
    """Descriptive statistics of the terminal price distribution."""
    return {
        "mean": float(np.mean(terminal_prices)),
        "median": float(np.median(terminal_prices)),
        "std": float(np.std(terminal_prices, ddof=1)),
        "skewness": float(stats.skew(terminal_prices)),
        "kurtosis": float(stats.kurtosis(terminal_prices)),   # excess kurtosis
        "min": float(np.min(terminal_prices)),
        "max": float(np.max(terminal_prices)),
        "pct5": float(np.percentile(terminal_prices, 5)),
        "pct25": float(np.percentile(terminal_prices, 25)),
        "pct75": float(np.percentile(terminal_prices, 75)),
        "pct95": float(np.percentile(terminal_prices, 95)),
        "mean_return": float(np.mean(terminal_returns)),
        "std_return": float(np.std(terminal_returns, ddof=1)),
    }


def _price_forecast(terminal_prices: np.ndarray, S0: float) -> Dict:
    """Pessimistic / central / optimistic forecast interval."""
    p5 = float(np.percentile(terminal_prices, 5))
    p95 = float(np.percentile(terminal_prices, 95))
    return {
        "mean_price": float(np.mean(terminal_prices)),
        "median_price": float(np.median(terminal_prices)),
        "pessimistic_p5": p5,
        "optimistic_p95": p95,
        "simulation_interval": p95 - p5,
        "pessimistic_return_pct": (p5 / S0 - 1) * 100,
        "optimistic_return_pct": (p95 / S0 - 1) * 100,
    }


def _probability_metrics(
    terminal_prices: np.ndarray,
    terminal_returns: np.ndarray,
    S0: float,
    target_ret: float,
    breach_pcts: List[float],
) -> Dict:
    """Probability estimates from simulated terminal distribution."""
    n = len(terminal_prices)

    probs: Dict = {
        "prob_profit": float(np.mean(terminal_prices > S0)),
        "prob_loss": float(np.mean(terminal_prices < S0)),
        "prob_target_return": float(np.mean(terminal_returns > target_ret)),
    }

    for pct in breach_pcts:
        upper = S0 * (1 + pct)
        lower = S0 * (1 - pct)
        probs[f"prob_above_{int(pct*100)}pct"] = float(np.mean(terminal_prices > upper))
        probs[f"prob_below_{int(pct*100)}pct"] = float(np.mean(terminal_prices < lower))

    return probs


def _var_cvar(terminal_returns: np.ndarray, var_levels: List[float]) -> Dict:
    """
    Value at Risk and Conditional VaR (Expected Shortfall).

    VaR at confidence level α is the loss exceeded in (1-α) of paths.
    CVaR is the average loss in the worst (1-α) fraction.

    Returns losses as positive numbers (e.g. 0.08 = 8% loss).
    """
    result: Dict = {}
    for level in var_levels:
        # Loss threshold: VaR is at the (1-level) quantile of returns
        var = float(-np.percentile(terminal_returns, (1 - level) * 100))
        # CVaR: average of returns worse than VaR
        cvar = float(-np.mean(terminal_returns[terminal_returns < -var]))
        result[f"var_{level}"] = var
        result[f"cvar_{level}"] = cvar
        logger.debug("  VaR %.0f%%=%.4f  CVaR %.0f%%=%.4f", level*100, var, level*100, cvar)
    return result


def _drawdown_metrics(paths: np.ndarray, thresholds: List[float]) -> Dict:
    """
    Compute per-path maximum drawdown and aggregate statistics.

    Maximum drawdown for path i:
        MDD_i = max over t of [ (running_peak_t - price_t) / running_peak_t ]

    Parameters
    ----------
    paths : np.ndarray, shape (n_paths, n_steps + 1)
    thresholds : list of float
        Drawdown levels for which to compute exceedance probabilities.

    Returns
    -------
    dict
        Includes ``max_drawdown_per_path`` array and aggregate stats.
    """
    # Running maximum for each path: shape (n_paths, n_steps+1)
    running_max = np.maximum.accumulate(paths, axis=1)

    # Drawdown at each step: shape (n_paths, n_steps+1)
    drawdowns = (running_max - paths) / running_max

    # Maximum drawdown per path
    max_dd_per_path = np.max(drawdowns, axis=1)  # shape (n_paths,)

    result = {
        "max_drawdown_per_path": max_dd_per_path,      # full array retained
        "avg_max_drawdown": float(np.mean(max_dd_per_path)),
        "median_max_drawdown": float(np.median(max_dd_per_path)),
        "worst_drawdown": float(np.max(max_dd_per_path)),
    }
    for thresh in thresholds:
        result[f"prob_dd_gt_{int(thresh*100)}pct"] = float(np.mean(max_dd_per_path > thresh))

    return result


def _volatility_comparison(
    paths: np.ndarray,
    processed_df: pd.DataFrame,
    n_steps: int,
) -> Dict:
    """
    Realised (historical) vs. simulated annualised volatility.

    Parameters
    ----------
    paths : np.ndarray
    processed_df : pd.DataFrame
        Must contain ``log_return``.
    n_steps : int
        Steps simulated (used to normalise simulated vol).
    """
    # Realised volatility from historical data
    hist_daily_vol = float(processed_df["log_return"].dropna().std())
    realised_annual = hist_daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Simulated path daily log returns
    log_ret_paths = np.log(paths[:, 1:] / paths[:, :-1])  # (n_paths, n_steps)
    sim_daily_vol = float(np.mean(np.std(log_ret_paths, axis=1, ddof=1)))
    simulated_annual = sim_daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    return {
        "realised_annual_vol": realised_annual,
        "simulated_annual_vol": simulated_annual,
        "vol_ratio": simulated_annual / realised_annual if realised_annual > 0 else np.nan,
    }


def _sharpe_sortino(
    paths: np.ndarray,
    S0: float,
    risk_free_rate: float,
    n_steps: int,
) -> Dict:
    """
    Sharpe and Sortino ratios across simulated paths.

    Sharpe_i = (annualised_return_i - rf) / annualised_vol_i
    Sortino_i = (annualised_return_i - rf) / downside_deviation_i

    Returns distribution of Sharpe across paths and a single Sortino
    computed on the mean-path basis.
    """
    # Per-path log returns
    log_ret_paths = np.log(paths[:, 1:] / paths[:, :-1])       # (n_paths, n_steps)

    # Annualised return per path
    ann_return = np.mean(log_ret_paths, axis=1) * TRADING_DAYS_PER_YEAR

    # Annualised volatility per path
    ann_vol = np.std(log_ret_paths, axis=1, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    ann_vol = np.where(ann_vol == 0, 1e-10, ann_vol)            # avoid div/0

    sharpe_per_path = (ann_return - risk_free_rate) / ann_vol   # (n_paths,)

    # Sortino: downside deviation (relative to 0 daily return)
    rf_daily = risk_free_rate / TRADING_DAYS_PER_YEAR
    downside_ret = np.minimum(log_ret_paths - rf_daily, 0.0)
    downside_dev = np.sqrt(np.mean(downside_ret ** 2, axis=1)) * np.sqrt(TRADING_DAYS_PER_YEAR)
    downside_dev = np.where(downside_dev == 0, 1e-10, downside_dev)
    sortino_per_path = (ann_return - risk_free_rate) / downside_dev

    # Terminal return for summary Sortino
    terminal_ret = paths[:, -1] / S0 - 1.0
    ann_terminal = (1 + terminal_ret) ** (TRADING_DAYS_PER_YEAR / max(n_steps, 1)) - 1

    return {
        "sharpe_per_path": sharpe_per_path,
        "mean_sharpe": float(np.mean(sharpe_per_path)),
        "median_sharpe": float(np.median(sharpe_per_path)),
        "sortino_per_path": sortino_per_path,
        "sortino": float(np.mean(sortino_per_path)),
        "mean_ann_return": float(np.mean(ann_return)),
        "mean_ann_vol": float(np.mean(ann_vol)),
    }


def _confidence_bands(paths: np.ndarray) -> Dict:
    """
    Compute percentile price bands across all paths for each time step.

    Returns
    -------
    dict
        Keys ``p5``, ``p25``, ``p50``, ``p75``, ``p95``: np.ndarray shape (n_steps+1,).
    """
    percentiles = [5, 25, 50, 75, 95]
    bands = {}
    for p in percentiles:
        bands[f"p{p}"] = np.percentile(paths, p, axis=0)
    return bands


def _log_key_metrics(metrics: Dict, model_name: str) -> None:
    """Log a concise summary of key risk metrics."""
    t = metrics["terminal"]
    vc = metrics["var_cvar"]
    p = metrics["probabilities"]
    dd = metrics["drawdown"]
    ss = metrics["sharpe_sortino"]
    S0 = metrics["S0"]

    logger.info(
        "[%s] Terminal Price → mean=%.0f  median=%.0f  p5=%.0f  p95=%.0f",
        model_name, t["mean"], t["median"], t["pct5"], t["pct95"],
    )
    logger.info(
        "[%s] VaR95=%.2f%%  CVaR95=%.2f%%  VaR99=%.2f%%  CVaR99=%.2f%%",
        model_name,
        vc.get("var_0.95", 0) * 100, vc.get("cvar_0.95", 0) * 100,
        vc.get("var_0.99", 0) * 100, vc.get("cvar_0.99", 0) * 100,
    )
    logger.info(
        "[%s] P(profit)=%.1f%%  P(loss)=%.1f%%  P(>target)=%.1f%%",
        model_name,
        p["prob_profit"] * 100, p["prob_loss"] * 100, p["prob_target_return"] * 100,
    )
    logger.info(
        "[%s] AvgMaxDD=%.2f%%  WorstDD=%.2f%%  Sharpe=%.3f  Sortino=%.3f",
        model_name,
        dd["avg_max_drawdown"] * 100, dd["worst_drawdown"] * 100,
        ss["mean_sharpe"], ss["sortino"],
    )
