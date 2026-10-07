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


"""
MAD Volatility Trail: median center, MAD-scaled bands, ATR floor, one-sided
ratcheting trail, regime state (bull/bear). Independent re-implementation
of the MAD_TRAIL_IMPLEMENTATION.md spec, adapted to this codebase's
precompute-once-per-symbol convention (see indicators.precompute_daily_
series's docstring for why this is safe: every step below depends only on
data up to and including that row, never anything after).

EXPERIMENTAL, backtest-only, not wired into the live screener/scorer.
Design choice (explicit request: "implement... on our top 20 watchlist"):
this module supplies ONLY the entry-trigger/stop/exit signal. WHICH stocks
are eligible on a given day still comes from the existing, unchanged core
momentum ranking (backtest.rank_universe_asof) -- the MAD trail decides
WHEN to buy/sell among that top-20, not which stocks are good. Mirrors the
architecture already used this session for the HA-trend and EMA-stack-
pullback experiments (separate strategy module + day-loop script, core
screener untouched).
"""

import numpy as np
import pandas as pd

import indicators

MAD_TRAIL_DEFAULTS = {
    "mt_med_len": 30,
    "mt_mad_len": 30,
    "mt_mad_scale": 1.4826,
    "mt_dev_factor": 2.0,
    "mt_use_atr_floor": True,
    "mt_atr_len": 14,
    "mt_atr_floor_mult": 1.0,
    "mt_slope_look": 3,
    "mt_entry_window": 5,
}


def cfg_from_strategy(cfg: dict) -> dict:
    """Maps config.STRATEGY's mad_stop_* keys onto this module's own mt_*
    naming (see MAD_TRAIL_DEFAULTS) -- the single shared mapping every
    caller (backtest.py, indicators.compute_snapshot, live_rebalance.py)
    uses, so their MAD-stop parameters can never quietly drift apart."""
    d = dict(MAD_TRAIL_DEFAULTS)
    d["mt_med_len"] = cfg.get("mad_stop_med_len", d["mt_med_len"])
    d["mt_mad_len"] = cfg.get("mad_stop_mad_len", d["mt_mad_len"])
    d["mt_dev_factor"] = cfg.get("mad_stop_dev_factor", d["mt_dev_factor"])
    d["mt_atr_floor_mult"] = cfg.get("mad_stop_atr_floor_mult", d["mt_atr_floor_mult"])
    return d


def _rolling_mad(close: pd.Series, med: pd.Series, n: int) -> pd.Series:
    """Median of |close - median_t| over the trailing n bars, deviations
    measured from the CURRENT median at each point (per the spec) -- can't
    use a plain pandas rolling call on a fixed series because of that, so
    this stays a per-bar loop same as the reference implementation. O(n)
    per bar (numpy median over a small window), fine for ~1400 bars/symbol."""
    c = close.to_numpy()
    m = med.to_numpy()
    out = np.empty(len(c))
    for i in range(len(c)):
        lo = max(0, i - n + 1)
        out[i] = np.median(np.abs(c[lo : i + 1] - m[i]))
    return pd.Series(out, index=close.index)


def precompute_mad_trail(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One-time per-symbol precompute of the full MAD trail: median, mad,
    atr, lower/upper (one-sided ratcheting bands), regime (+1/-1),
    flip_bull/flip_bear, slope_up. Every value at row i depends only on
    rows [0..i] -- safe to compute once over full history and look up by
    date later, same convention as every other precomputed indicator in
    this codebase (see indicators.precompute_daily_series)."""
    close = df["close"]
    med_len = cfg.get("mt_med_len", 30)
    mad_len = cfg.get("mt_mad_len", 30)
    mad_scale = cfg.get("mt_mad_scale", 1.4826)
    dev_factor = cfg.get("mt_dev_factor", 2.0)
    atr_len = cfg.get("mt_atr_len", 14)
    slope_look = cfg.get("mt_slope_look", 3)

    median = close.rolling(med_len, min_periods=1).median()
    mad = _rolling_mad(close, median, mad_len)
    atr = indicators.atr(df, atr_len)

    width = mad * mad_scale * dev_factor
    if cfg.get("mt_use_atr_floor", True):
        width = np.maximum(width, atr * cfg.get("mt_atr_floor_mult", 1.0))

    raw_lower = (median - width).to_numpy()
    raw_upper = (median + width).to_numpy()
    c = close.to_numpy()
    n = len(df)
    lower = np.empty(n)
    upper = np.empty(n)
    regime = np.empty(n, dtype=int)
    for i in range(n):
        if i == 0 or np.isnan(raw_lower[i]) or np.isnan(raw_upper[i]):
            lower[i], upper[i] = raw_lower[i], raw_upper[i]
            regime[i] = 1
            continue
        # one-sided ratchet: support only rises while price holds above it,
        # resistance only falls while price holds below it (causal -- uses
        # only close[i-1] and the prior bar's own band values)
        lower[i] = max(raw_lower[i], lower[i - 1]) if c[i - 1] > lower[i - 1] else raw_lower[i]
        upper[i] = min(raw_upper[i], upper[i - 1]) if c[i - 1] < upper[i - 1] else raw_upper[i]
        regime[i] = (
            (-1 if c[i] < lower[i] else 1) if regime[i - 1] == 1 else (1 if c[i] > upper[i] else -1)
        )

    out = pd.DataFrame(
        {
            "median": median,
            "mad": mad,
            "atr": atr,
            "lower": lower,
            "upper": upper,
            "regime": regime,
        },
        index=df.index,
    )
    out["flip_bull"] = (out["regime"] == 1) & (out["regime"].shift(1) == -1)
    out["flip_bear"] = (out["regime"] == -1) & (out["regime"].shift(1) == 1)
    out["slope_up"] = (out["median"] > out["median"].shift(slope_look)) if slope_look > 0 else True
    # "bars since last bull flip" -- lets the day-loop check `<= entry_window`
    # without re-scanning history each day. NaN/False flip_bull never resets
    # this below a running count, so a stock that flipped bull 3 bars ago
    # and has stayed regime==1 since reads 3, 4, 5... (matches the spec's
    # `i - last_flip < entry_window` check exactly).
    flip_idx = pd.Series(np.where(out["flip_bull"], np.arange(n), np.nan), index=out.index)
    flip_idx = flip_idx.ffill()
    out["bars_since_bull_flip"] = np.arange(n) - flip_idx.to_numpy()
    return out
