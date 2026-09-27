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
Overhead-resistance detection: identifies multi-year price zones a stock has
repeatedly reversed at in the past, and scores how much "clean room" an
entry candidate has before running into the nearest one above its current
price.

Why this matters for a long-only momentum strategy (not "support" in the
usual sense -- see module name): a swing high or low from years ago leaves
behind a price level where real buying/selling interest previously changed
hands. When price rallies back UP into that level, latent overhead supply
(traders who bought there before and are relieved to finally exit near
even) can resurface and cap the rally -- a plausible mechanism behind
entries that stall and reverse into their stop shortly after being taken,
even though every other momentum/trend signal looked fine at entry.

Point-in-time safety: a swing pivot at bar i isn't knowable until `window`
bars AFTER it (you need to see the price fail to make a new extreme on
either side to confirm it was really a local turning point) -- pivots are
tagged with the date they become confirmed, and every zone/clearance
computation below filters to pivots confirmed as of the query date, never
using data that wouldn't have been available yet.

Performance: pivot count is small and roughly constant per year of history
(unlike the daily bar count, which is what made naive per-day
recomputation elsewhere in this codebase O(T^2) -- see indicators.
precompute_daily_series's docstring) so precompute_pivots() runs ONCE per
symbol over the full deep-history series, and the per-rebalance-day lookup
(resistance_clearance_asof) only ever filters/clusters that small
precomputed set, not the raw daily candles.
"""


import numpy as np
import pandas as pd


def precompute_pivots(long_df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Every confirmed swing-high/low in `long_df` (needs "high"/"low"
    columns) -- a bar is a swing point if its high (or low) is the most
    extreme value in a `window`-bar radius on each side. Returns a
    DataFrame with one row per pivot: pivot_date (when it happened),
    price, confirmed_date (pivot_date + `window` trading days -- the
    earliest date this pivot could legitimately be used).

    Both swing highs AND swing lows count as "touches" of a price level
    for the zone-strength purposes downstream -- either kind reflects a
    point where the prevailing direction reversed, which is what makes a
    level behaviorally significant, not which side of it price approached
    from.

    Empty (not an error) if `long_df` has fewer than 2*window+1 rows --
    callers treat "no pivots yet" as "no zone data", not a failure."""
    if len(long_df) < 2 * window + 1:
        return pd.DataFrame(columns=["pivot_date", "price", "confirmed_date"])

    high, low = long_df["high"], long_df["low"]
    roll_max = high.rolling(2 * window + 1, center=True).max()
    roll_min = low.rolling(2 * window + 1, center=True).min()
    is_high = (high == roll_max) & roll_max.notna()
    is_low = (low == roll_min) & roll_min.notna()

    n = len(long_df)
    confirmed_pos = np.arange(n) + window
    confirmed_dates = long_df.index[np.minimum(confirmed_pos, n - 1)]

    hi_pos = np.where(is_high.to_numpy())[0]
    lo_pos = np.where(is_low.to_numpy())[0]
    rows = [(long_df.index[p], float(high.iloc[p]), confirmed_dates[p]) for p in hi_pos] + [
        (long_df.index[p], float(low.iloc[p]), confirmed_dates[p]) for p in lo_pos
    ]
    return pd.DataFrame(rows, columns=["pivot_date", "price", "confirmed_date"])


def _cluster(prices: np.ndarray, tolerance_pct: float) -> pd.DataFrame:
    """Greedy 1D clustering: sorted prices within `tolerance_pct` of their
    cluster's running mean get grouped together. Returns one row per
    cluster (zone): price (mean of its members), strength (touch count).
    Simple by design -- with typically well under a few hundred points
    per symbol, there's no need for anything fancier than sort + walk."""
    if len(prices) == 0:
        return pd.DataFrame(columns=["price", "strength"])
    prices = np.sort(prices)
    zones = []
    cluster = [prices[0]]
    for p in prices[1:]:
        cluster_mean = sum(cluster) / len(cluster)
        if (p - cluster_mean) / cluster_mean <= tolerance_pct:
            cluster.append(p)
        else:
            zones.append((sum(cluster) / len(cluster), len(cluster)))
            cluster = [p]
    zones.append((sum(cluster) / len(cluster), len(cluster)))
    return pd.DataFrame(zones, columns=["price", "strength"])


def resistance_clearance_asof(
    pivots: pd.DataFrame,
    current_price: float,
    date,
    lookback_years: float = 5.0,
    tolerance_pct: float = 0.03,
    search_pct: float = 0.20,
) -> float | None:
    """How much "clean room" `current_price` has before the nearest
    confirmed overhead zone, as of `date` -- higher is better (more room
    to run before hitting resistance), matching every other score.py
    factor's convention, so this plugs into the weighted-sum score
    directly with no sign flip.

    Only considers pivots from the trailing `lookback_years` (a receding
    window, not a fixed anchor -- "multi-year" relative to `date`, not to
    today) that are already CONFIRMED as of `date` (see precompute_pivots).
    Clusters whatever's left into zones (see _cluster), keeps only zones
    at or above current_price within `search_pct` (an overhead zone more
    than search_pct away is too far to threaten this entry either way),
    and returns distance_to_nearest / (1 + its_strength) -- a strong zone
    right next to the price shrinks the effective clearance sharply; a
    weak or distant zone barely matters.

    None (not a numeric fallback) when there's no usable pivot history or
    no zone found in range -- callers z-score this column and .fillna(0)
    the result (same pattern as the sector-RS bonus), so an unknown/no-
    zone stock contributes neutrally to the score rather than being
    artificially favored or penalized for missing data."""
    if pivots.empty or current_price <= 0:
        return None
    cutoff_date = pd.Timestamp(date) - pd.DateOffset(years=lookback_years)
    visible = pivots[(pivots["confirmed_date"] <= date) & (pivots["pivot_date"] >= cutoff_date)]
    if visible.empty:
        return None

    upper_bound = current_price * (1 + search_pct)
    lower_bound = current_price * (1 - tolerance_pct)  # catches a zone price is already sitting inside
    band = visible[(visible["price"] >= lower_bound) & (visible["price"] <= upper_bound)]
    if band.empty:
        return None

    zones = _cluster(band["price"].to_numpy(), tolerance_pct)
    above = zones[zones["price"] >= current_price]
    if above.empty:
        return None

    nearest = above.loc[above["price"].idxmin()]
    distance_pct = (nearest["price"] - current_price) / current_price
    return float(distance_pct / (1 + nearest["strength"]))
