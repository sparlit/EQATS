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
Day-state feature extraction — the observable "context" for strategy selection.

All features are computed from data available at 9:45 IST (end of the
observation window) plus prior sessions. Strictly causal: nothing here can
see past 9:45 of the trading day.

These features are what published research says actually carries information
about how the rest of the day unfolds:
  - Overnight gap size (vs prior range) separates gap-fill days from gap-and-go
  - First-30-min return predicts late-day direction (Gao/Han/Li/Zhou, JFE 2018)
  - Opening range expansion vs norm separates trend days from range days
  - Opening volume confirms (or denies) genuine participation
"""

import pandas as pd

# Fixed feature order — selector relies on this for vector distances.
FEATURES = [
    "gap_pct",  # overnight gap, % of prev close
    "gap_vs_range",  # gap / prior-day high-low range (gap "severity")
    "first30_ret",  # 9:15→9:45 return %  (signed — direction matters)
    "rel_first30_ret",  # stock first-30 return minus Nifty proxy first-30 return
    "or_range_pct",  # opening range as % of price (raw volatility)
    "or_expansion",  # opening range / prior-day range (trend-day tell)
    "or_close_pos",  # where 9:45 close sits inside opening range: 0=low, 1=high
    "prev_range_pct",  # prior-day high-low range as % of prior close
    "vol_ratio",  # first-30 volume vs prior days' first-30 average
    "first30_turnover_cr",  # first-30 traded value in INR crore; liquidity/cost proxy
    "adx",  # trend strength at 9:45 (warmed up on prior days)
    "vwap_crosses",  # choppiness: VWAP crossings in observation window
    "atr_pct",  # ATR as % of price (volatility level)
    "prev_day_ret",  # prior session close-to-close return %
    "mkt_first30_ret",  # Nifty proxy 9:15→9:45 return % (market-level state)
    # Cross-sectional "in play" ranks — percentile (0..1) of this stock vs the
    # whole scanned universe TODAY. Zarattini/Barbon/Aziz: relative volume rank
    # is the single biggest determinant of intraday momentum profitability.
    # Default 0.5 (median) when only one symbol is scanned (legacy mode).
    "vol_ratio_rank",  # first-30 relative volume, ranked across universe
    "gap_abs_rank",  # |overnight gap|, ranked across universe
    "or_expansion_rank",  # opening-range expansion, ranked across universe
]

# (feature, rank_feature) pairs used by apply_cross_sectional_ranks
_RANK_SPECS = [
    ("vol_ratio", "vol_ratio_rank", False),
    ("gap_pct", "gap_abs_rank", True),  # rank on |gap|
    ("or_expansion", "or_expansion_rank", False),
]


def apply_cross_sectional_ranks(features_by_symbol: dict) -> None:
    """
    Mutates each symbol's feature dict, adding percentile ranks (0..1) of the
    base features across all symbols scanned for the same day. Causal: uses
    only 9:45 information for every symbol.
    """
    feats = [f for f in features_by_symbol.values() if f]
    n = len(feats)
    if n < 2:
        return
    for base, rank_key, use_abs in _RANK_SPECS:
        vals = sorted(abs(f.get(base, 0.0)) if use_abs else f.get(base, 0.0) for f in feats)
        for f in feats:
            v = abs(f.get(base, 0.0)) if use_abs else f.get(base, 0.0)
            below = sum(1 for x in vals if x < v)
            f[rank_key] = round(below / (n - 1), 3)


def compute_day_state(obs_window: pd.DataFrame, warmup: pd.DataFrame, market_obs: pd.DataFrame = None) -> dict:
    """
    obs_window: enriched 5m bars for today, 9:15–9:45 only (from indicators.compute_all)
    warmup:     raw OHLCV 5m bars for the prior sessions (oldest first)
    market_obs: Nifty proxy bars for today's observation window (optional)

    Returns {feature: float} in FEATURES order, or None if inputs are unusable.
    """
    if obs_window is None or obs_window.empty or warmup is None or warmup.empty:
        return None

    today_open = float(obs_window.iloc[0]["open"])
    last = obs_window.iloc[-1]
    close_945 = float(last["close"])
    or_high = float(obs_window["high"].max())
    or_low = float(obs_window["low"].min())
    or_mid = (or_high + or_low) / 2 or 1.0

    # Prior sessions, grouped by date
    warm_days = list(warmup.groupby(warmup.index.date))
    _, prev_df = warm_days[-1]
    prev_close = float(prev_df.iloc[-1]["close"])
    prev_open = float(prev_df.iloc[0]["open"])
    prev_range = float(prev_df["high"].max() - prev_df["low"].min()) or 1e-9

    # First-30-min volume across prior sessions (same clock window ≈ first 6 bars)
    prior_f30_vols = [float(d.iloc[:6]["volume"].sum()) for _, d in warm_days]
    avg_f30_vol = (sum(prior_f30_vols) / len(prior_f30_vols)) or 1.0
    today_f30_vol = float(obs_window["volume"].sum())

    gap = today_open - prev_close

    mkt_ret = 0.0
    if market_obs is not None and not market_obs.empty:
        m_open = float(market_obs.iloc[0]["open"])
        m_close = float(market_obs.iloc[-1]["close"])
        if m_open:
            mkt_ret = round((m_close - m_open) / m_open * 100, 3)

    first30_ret = round((close_945 - today_open) / today_open * 100, 3) if today_open else 0.0
    or_span = or_high - or_low

    return {
        "gap_pct": round(gap / prev_close * 100, 3) if prev_close else 0.0,
        "gap_vs_range": round(gap / prev_range, 3),
        "first30_ret": first30_ret,
        "rel_first30_ret": round(first30_ret - mkt_ret, 3),
        "or_range_pct": round((or_high - or_low) / or_mid * 100, 3),
        "or_expansion": round((or_high - or_low) / prev_range, 3),
        "or_close_pos": round((close_945 - or_low) / or_span, 3) if or_span else 0.5,
        "prev_range_pct": round(prev_range / prev_close * 100, 3) if prev_close else 0.0,
        "vol_ratio": round(today_f30_vol / avg_f30_vol, 3),
        "first30_turnover_cr": round(close_945 * today_f30_vol / 10_000_000, 3),
        "adx": round(float(last.get("adx", 0.0)), 2),
        "vwap_crosses": float(last.get("vwap_crosses", 0.0)),
        "atr_pct": round(float(last.get("atr", 0.0)) / close_945 * 100, 3) if close_945 else 0.0,
        "prev_day_ret": round((prev_close - prev_open) / prev_open * 100, 3) if prev_open else 0.0,
        "mkt_first30_ret": mkt_ret,
        # Median defaults; overwritten by apply_cross_sectional_ranks in scan mode
        "vol_ratio_rank": 0.5,
        "gap_abs_rank": 0.5,
        "or_expansion_rank": 0.5,
    }
