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


"""Signal evaluation runner — combines all eval modules for one signal."""


import logging

import pandas as pd
from nse_alpha.eval.alignment import align_signal_to_returns
from nse_alpha.eval.costs import (
    SENSITIVITY_COST_BPS,
    compute_capacity,
    compute_net_returns,
)
from nse_alpha.eval.ic import (
    DEFAULT_HORIZONS,
    compute_ic_decay,
    compute_ic_series,
    compute_ic_stats,
    fit_ic_halflife,
)
from nse_alpha.eval.portfolio import (
    compute_cumulative_returns,
    compute_decile_portfolios,
    compute_ls_spread,
    compute_sharpe,
)
from nse_alpha.eval.preprocessing import preprocess
from nse_alpha.eval.turnover import compute_turnover, compute_weights_from_deciles

logger = logging.getLogger(__name__)


def evaluate_signal(
    name: str,
    family: str,
    raw_scores: pd.Series,
    panel: pd.DataFrame,
    *,
    sector_map: dict[str, str] | None = None,
    log_adv: pd.Series | None = None,
    horizons: list[int] | None = None,
) -> dict[str, object]:
    """Run the full evaluation pipeline for one signal.

    Parameters
    ----------
    name:
        Signal name.
    family:
        Signal family (e.g. "Momentum").
    raw_scores:
        Raw signal series, MultiIndex ``(date, symbol)``.
    panel:
        Full tidy panel.
    sector_map:
        Optional sector neutralisation mapping.
    log_adv:
        Optional log-ADV series for size neutralisation.
    horizons:
        IC decay horizons.  Defaults to ``DEFAULT_HORIZONS``.

    Returns
    -------
    dict
        All evaluation metrics for the signal.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    logger.info("Evaluating signal: %s (%s)", name, family)

    # 1. Preprocess
    scores = preprocess(raw_scores, sector_map=sector_map, log_adv=log_adv)

    # 2. Align to h=1 forward returns for IC stats
    aligned_h1 = align_signal_to_returns(scores, panel, horizon=1)

    # 3. IC stats at h=1
    ic_series = compute_ic_series(aligned_h1)
    ic_stats = compute_ic_stats(ic_series)

    # 4. IC decay
    ic_decay_df = compute_ic_decay(scores, panel, horizons=horizons)
    half_life = fit_ic_halflife(ic_decay_df)

    # 5. Portfolio
    decile_rets = compute_decile_portfolios(aligned_h1)
    ls_spread = compute_ls_spread(decile_rets)
    gross_sharpe = compute_sharpe(ls_spread)

    # 6. Turnover
    weights = compute_weights_from_deciles(aligned_h1)
    turnover = compute_turnover(weights)

    # 7. Net Sharpe at multiple cost levels
    net_sharpes: dict[float, float] = {}
    for cost_bps in SENSITIVITY_COST_BPS:
        net_ret = compute_net_returns(ls_spread, turnover, cost_bps)
        net_sharpes[cost_bps] = compute_sharpe(net_ret)

    # 8. Capacity
    capacity_cr = compute_capacity(panel, weights)

    # 9. Cumulative returns (at default 15 bps)
    net_ret_15 = compute_net_returns(ls_spread, turnover, cost_bps=15.0)
    cumulative = compute_cumulative_returns(ls_spread, net_ret_15)

    return {
        "signal": name,
        "family": family,
        "ic_mean": ic_stats["ic_mean"],
        "ic_std": ic_stats["ic_std"],
        "ic_tstat": ic_stats["ic_tstat"],
        "ir": ic_stats["ir"],
        "turnover": turnover,
        "gross_sharpe": gross_sharpe,
        "net_sharpe_5bps": net_sharpes[5.0],
        "net_sharpe_15bps": net_sharpes[15.0],
        "net_sharpe_30bps": net_sharpes[30.0],
        "capacity_cr": capacity_cr,
        "half_life_days": half_life,
        # Detailed series for plots
        "_ic_series": ic_series,
        "_ic_decay": ic_decay_df,
        "_decile_rets": decile_rets,
        "_ls_spread": ls_spread,
        "_cumulative": cumulative,
    }
