"""
backtest.py — Walk-Forward Validation
======================================

Splits historical data into rolling train/test windows and measures
how well each simulation model's predicted distribution matches what
actually happened in the test period.

Methodology
-----------
1. For each window:
   a. Train on data up to split point T_i.
   b. Simulate paths starting from the last price at T_i.
   c. Compare simulated terminal distribution against actual price at T_i + test_window.
   d. Record whether the actual outcome falls inside the simulated 90% CI.
2. Report coverage across all windows (should ≈ 90% if well-calibrated).
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

from .data_pipeline import _compute_features, _extract_gbm_params

logger = logging.getLogger(__name__)


def run_walkforward(
    processed_df: pd.DataFrame,
    cfg: dict,
    simulator_fn: Callable,
    model_name: str = "GBM",
) -> Dict:
    """
    Execute walk-forward validation for a given simulator function.

    Parameters
    ----------
    processed_df : pd.DataFrame
        Full processed dataset (from data_pipeline).
    cfg : dict
        Full configuration dictionary.
    simulator_fn : Callable
        A function with signature ``(params, processed_df, n_steps, n_paths, seed) → np.ndarray``.
        Should accept and ignore extra kwargs gracefully.
    model_name : str
        Label for logging.

    Returns
    -------
    dict
        ``coverage_90``: fraction of windows where actual fell in simulated 90% CI.
        ``windows``: list of per-window result dicts.
        ``summary``: textual summary.
    """
    bt_cfg = cfg["backtest"]
    sim_cfg = cfg["simulation"]
    test_window = bt_cfg["test_window_days"]
    n_windows = bt_cfg["n_windows"]
    n_paths = sim_cfg["n_paths"]
    seed = sim_cfg["seed"]

    df = processed_df.dropna(subset=["log_return"]).copy()
    total_days = len(df)

    # Minimum training data needed for parameter estimation
    min_train = 252 * 2

    # Determine window positions
    # Walk backwards from the end: last test ends at df[-1], test starts at df[-1-test_window]
    window_results: List[Dict] = []

    for i in range(n_windows):
        # Test period ends at this index
        test_end_idx = total_days - i * test_window - 1
        test_start_idx = test_end_idx - test_window
        train_end_idx = test_start_idx - 1

        if train_end_idx < min_train:
            logger.warning("Window %d: not enough training data (%d days). Skipping.", i, train_end_idx)
            continue

        train_df = df.iloc[:train_end_idx + 1]
        actual_price_at_test_start = float(train_df["Close"].iloc[-1])
        actual_price_at_test_end = float(df["Close"].iloc[test_end_idx])

        # Compute params from training data only
        train_params = _extract_gbm_params(train_df, cfg)
        train_params["S0"] = actual_price_at_test_start

        # Simulate from training params
        try:
            paths = simulator_fn(
                params=train_params,
                processed_df=train_df,
                n_steps=test_window,
                n_paths=n_paths,
                seed=seed + i,
            )
        except Exception as exc:
            logger.warning("Window %d: simulation failed (%s). Skipping.", i, exc)
            continue

        terminal_prices = paths[:, -1]
        p5 = float(np.percentile(terminal_prices, 5))
        p95 = float(np.percentile(terminal_prices, 95))
        in_band = p5 <= actual_price_at_test_end <= p95

        actual_return = (actual_price_at_test_end / actual_price_at_test_start) - 1.0
        mean_sim_return = float(np.mean(terminal_prices / actual_price_at_test_start - 1.0))

        window_results.append({
            "window": i,
            "train_end_date": str(train_df.index[-1].date()),
            "test_end_date": str(df.index[test_end_idx].date()),
            "actual_price_start": actual_price_at_test_start,
            "actual_price_end": actual_price_at_test_end,
            "actual_return_pct": actual_return * 100,
            "simulated_mean_return_pct": mean_sim_return * 100,
            "sim_p5": p5,
            "sim_p95": p95,
            "actual_in_90pct_band": in_band,
        })

        logger.info(
            "[%s] Window %d: actual=%.0f  p5=%.0f  p95=%.0f  in_band=%s",
            model_name, i, actual_price_at_test_end, p5, p95, in_band,
        )

    if not window_results:
        logger.warning("[%s] No valid backtest windows computed.", model_name)
        return {"coverage_90": np.nan, "windows": [], "summary": "Insufficient data."}

    coverage = float(np.mean([w["actual_in_90pct_band"] for w in window_results]))
    summary = (
        f"{model_name}: {len(window_results)} windows, "
        f"90%-band coverage = {coverage:.1%} "
        f"(target ≈ 90%)"
    )
    logger.info("[%s] Walk-forward result: %s", model_name, summary)

    return {
        "model": model_name,
        "coverage_90": coverage,
        "n_windows": len(window_results),
        "windows": window_results,
        "summary": summary,
    }
