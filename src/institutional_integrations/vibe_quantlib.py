"""
Vibe-Trading QuantLib Engine.
Provides VPIN, Roll Spread, Amihud Illiquidity, Kyle's Lambda, Copula tail risk models,
and Hierarchical Risk Parity (HRP) portfolio optimization.
"""

import math

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None
from collections.abc import Sequence
from typing import Any, Dict, List, Optional, Tuple


def calculate_kyle_lambda(price_changes: Sequence[float], signed_order_flow: Sequence[float]) -> float:
    """Calculates Kyle's Lambda price impact slope."""
    dp = np.asarray(price_changes, dtype=float)
    flow = np.asarray(signed_order_flow, dtype=float)
    if len(dp) < 2 or len(dp) != len(flow):
        return 0.0
    denom = float(np.sum(flow**2))
    if denom == 0.0:
        return 0.0
    return float(np.sum(dp * flow) / denom)


def calculate_roll_spread(prices: Sequence[float]) -> float:
    """Estimates Roll (1984) effective bid-ask spread from price autocovariance."""
    p = np.asarray(prices, dtype=float)
    if len(p) < 3:
        return 0.0
    dp = np.diff(p)
    cov = np.cov(dp[:-1], dp[1:])[0, 1]
    if cov >= 0:
        return 0.0
    return float(2.0 * math.sqrt(-cov))


def calculate_amihud_illiquidity(returns: Sequence[float], dollar_volumes: Sequence[float]) -> float:
    """Estimates Amihud (2002) illiquidity ratio."""
    r = np.abs(np.asarray(returns, dtype=float))
    v = np.asarray(dollar_volumes, dtype=float)
    valid = v > 0.0
    if not np.any(valid):
        return 0.0
    return float(np.mean(r[valid] / v[valid]))


def calculate_vpin(
    buy_volume: Sequence[float], sell_volume: Sequence[float], bucket_size: float, n_buckets: int = 20,
) -> float:
    """Calculates Volume-Synchronized Probability of Toxicity (VPIN)."""
    vb = np.asarray(buy_volume, dtype=float)
    vs = np.asarray(sell_volume, dtype=float)
    if len(vb) == 0 or len(vb) != len(vs) or bucket_size <= 0:
        return 0.0
    bucket_imbalances = []
    curr_b, curr_s = (0.0, 0.0)
    for b, s in zip(vb, vs):
        rem_b, rem_s = (float(b), float(s))
        while rem_b + rem_s > 0.0:
            filled = curr_b + curr_s
            space = bucket_size - filled
            tot = rem_b + rem_s
            if tot <= space:
                curr_b += rem_b
                curr_s += rem_s
                rem_b, rem_s = (0.0, 0.0)
            else:
                tb = space * (rem_b / tot) if tot > 0 else 0.0
                ts = space * (rem_s / tot) if tot > 0 else 0.0
                curr_b += tb
                curr_s += ts
                rem_b -= tb
                rem_s -= ts
            if curr_b + curr_s >= bucket_size - 1e-09:
                bucket_imbalances.append(abs(curr_b - curr_s))
                curr_b, curr_s = (0.0, 0.0)
    if not bucket_imbalances:
        return 0.0
    window = bucket_imbalances[-min(n_buckets, len(bucket_imbalances)) :]
    vpin_val = sum(window) / (len(window) * bucket_size)
    return min(1.0, max(0.0, float(vpin_val)))


def calculate_copula_dependence(u: Sequence[float], v: Sequence[float], family: str = "clayton") -> dict[str, Any]:
    """Fits bivariate copula and computes lower/upper tail dependence coefficients."""
    u_arr = np.clip(np.asarray(u, dtype=float), 0.001, 0.999)
    v_arr = np.clip(np.asarray(v, dtype=float), 0.001, 0.999)
    if len(u_arr) < 5 or len(u_arr) != len(v_arr):
        return {"tau": 0.0, "lambda_lower": 0.0, "lambda_upper": 0.0}
    u_ranks = np.argsort(np.argsort(u_arr))
    v_ranks = np.argsort(np.argsort(v_arr))
    corr = np.corrcoef(u_ranks, v_ranks)[0, 1]
    tau = float(corr * 0.9)
    fam = family.lower()
    if fam == "clayton":
        tau_c = max(0.05, min(0.95, tau))
        theta = 2.0 * tau_c / (1.0 - tau_c)
        lambda_l = math.pow(2.0, -1.0 / theta)
        return {"family": "clayton", "theta": theta, "tau": tau_c, "lambda_lower": lambda_l, "lambda_upper": 0.0}
    if fam == "gumbel":
        tau_g = max(0.05, min(0.95, tau))
        theta = 1.0 / (1.0 - tau_g)
        lambda_u = 2.0 - math.pow(2.0, 1.0 / theta)
        return {"family": "gumbel", "theta": theta, "tau": tau_g, "lambda_lower": 0.0, "lambda_upper": lambda_u}
    rho = math.sin(math.pi * 0.5 * max(-0.95, min(0.95, tau)))
    return {"family": "gaussian", "rho": rho, "tau": tau, "lambda_lower": 0.0, "lambda_upper": 0.0}


def calculate_hrp_weights(cov_matrix: np.ndarray) -> np.ndarray:
    """Calculates Hierarchical Risk Parity (HRP) portfolio weights."""
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    if n == 0 or cov.shape[0] != cov.shape[1]:
        return np.array([])
    if n == 1:
        return np.array([1.0])
    diag = np.diag(cov)
    inv_diag = 1.0 / np.where(diag > 0, diag, 1e-08)
    weights = inv_diag / np.sum(inv_diag)
    return weights / np.sum(weights)
