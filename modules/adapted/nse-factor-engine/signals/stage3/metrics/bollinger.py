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
Stage 3 — Metric: Bollinger Bands

Computes 20-day Bollinger Bands and derived metrics for each stock as of T.

  Middle Band  = 20D SMA of close as of T
  Std_20       = 20D rolling std dev of close (ddof=1)
  Upper Band   = Middle + (2 × Std_20)
  Lower Band   = Middle - (2 × Std_20)
  %B           = (Close_T - Lower Band) / (Upper Band - Lower Band)
  Bandwidth    = (Upper Band - Lower Band) / Middle × 100  [normalised width]

Bandwidth is computed as of T (curr_wk) and the 3 prior weekly closes
(prev_wk, prev_2wk, prev_3wk) using actual trading days from prices.parquet —
no calendar arithmetic.

  bb_bandwidth_curr_wk  : bandwidth as of T          (latest trading day)
  bb_bandwidth_prev_wk  : bandwidth as of T-5 trading days
  bb_bandwidth_prev_2wk : bandwidth as of T-10 trading days
  bb_bandwidth_prev_3wk : bandwidth as of T-15 trading days
  bb_squeeze            : 'Y' if curr_wk bandwidth < all three prior weeks, else 'N'
                          (bandwidth at 4-week low = coiled spring condition)

Interpretation (%B):
  > 1.0     : Price above upper band — extended
  0.5 – 1.0 : Upper half of bands — bullish
  0.0 – 0.5 : Lower half of bands — cautious
  < 0.0     : Price below lower band — oversold

Bandwidth (self-normalised — compare against own history, not cross-stock):
  bb_squeeze = 'Y'              → bands at tightest in 4 weeks, big move imminent
  bb_bandwidth_curr_wk rising   → volatility expanding, move underway; watch %B for direction

Breakout setup (all three required):
  1. bb_squeeze = 'Y' (bandwidth contracting over 4 weeks)
  2. bb_pct_b crosses above 1.0 (first close outside upper band)
  3. MFI rising above 55 (volume participating)

False breakout:
  bb_pct_b > 1.0 but MFI < 45 → price above band without volume → likely snap back

Combined with EMA distance:
  bb_pct_b > 1.0 + dist_ema_50 > 20% = doubly extended, highest reversion risk

Inputs:
  prices : full prices.parquet dataframe (all dates up to and including T)
  T      : as-of date (pd.Timestamp)

Returns:
  DataFrame with columns:
    [symbol, bb_middle, bb_upper, bb_lower, bb_pct_b,
     bb_bandwidth_curr_wk, bb_bandwidth_prev_wk,
     bb_bandwidth_prev_2wk, bb_bandwidth_prev_3wk, bb_squeeze]
  Symbols with fewer than 20 price observations return NaN for band columns.
  If upper == lower (zero std), %B and bandwidth columns are NaN.
"""

import numpy as np
import pandas as pd

BB_PERIOD = 20
BB_STD = 2
TRADING_DAYS_W = 5  # trading days per week


def _bandwidth_as_of(close: pd.Series) -> float:
    """
    Compute Bollinger bandwidth for a close series whose last row is the as-of date.
    Returns NaN if fewer than BB_PERIOD rows or zero std.
    """
    close = close.dropna().reset_index(drop=True)
    if len(close) < BB_PERIOD:
        return np.nan
    window = close.iloc[-BB_PERIOD:]
    middle = window.mean()
    if middle == 0:
        return np.nan
    std = window.std(ddof=1)
    upper = middle + BB_STD * std
    lower = middle - BB_STD * std
    band_width = upper - lower
    if band_width == 0:
        return np.nan
    return round(band_width / middle * 100, 4)


def _compute_bb(close: pd.Series) -> dict:
    """
    Compute full Bollinger Band output for a single symbol's close series.
    close must already be sorted ascending and filtered to <= T.
    """
    close = close.dropna().reset_index(drop=True)
    nan_row = {
        "bb_middle": np.nan,
        "bb_upper": np.nan,
        "bb_lower": np.nan,
        "bb_pct_b": np.nan,
        "bb_bandwidth_curr_wk": np.nan,
        "bb_bandwidth_prev_wk": np.nan,
        "bb_bandwidth_prev_2wk": np.nan,
        "bb_bandwidth_prev_3wk": np.nan,
        "bb_squeeze": np.nan,
    }

    if len(close) < BB_PERIOD:
        return nan_row

    # ── Current week (T) ──
    window = close.iloc[-BB_PERIOD:]
    middle = window.mean()
    std = window.std(ddof=1)
    upper = middle + BB_STD * std
    lower = middle - BB_STD * std
    close_t = close.iloc[-1]
    band_width = upper - lower

    if band_width == 0 or middle == 0:
        pct_b = np.nan
        bw_curr = np.nan
    else:
        pct_b = round((close_t - lower) / band_width, 4)
        bw_curr = round(band_width / middle * 100, 4)

    # ── Prior weeks: slice close up to T-Nw and recompute bandwidth ──
    n = len(close)
    bw_1w = _bandwidth_as_of(close.iloc[: n - TRADING_DAYS_W]) if n > TRADING_DAYS_W else np.nan
    bw_2w = _bandwidth_as_of(close.iloc[: n - 2 * TRADING_DAYS_W]) if n > 2 * TRADING_DAYS_W else np.nan
    bw_3w = _bandwidth_as_of(close.iloc[: n - 3 * TRADING_DAYS_W]) if n > 3 * TRADING_DAYS_W else np.nan

    # ── Squeeze: curr bandwidth < all three prior weeks ──
    prior = [x for x in [bw_1w, bw_2w, bw_3w] if not np.isnan(x)]
    squeeze = ("Y" if bw_curr < min(prior) else "N") if not np.isnan(bw_curr) and len(prior) == 3 else np.nan

    return {
        "bb_middle": round(float(middle), 4),
        "bb_upper": round(float(upper), 4),
        "bb_lower": round(float(lower), 4),
        "bb_pct_b": pct_b,
        "bb_bandwidth_curr_wk": bw_curr,
        "bb_bandwidth_prev_wk": bw_1w,
        "bb_bandwidth_prev_2wk": bw_2w,
        "bb_bandwidth_prev_3wk": bw_3w,
        "bb_squeeze": squeeze,
    }


def compute(prices: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """
    Compute Bollinger Band metrics for every symbol in prices, as of T.

    Parameters
    ----------
    prices : DataFrame with columns [symbol, date, close, ...]
    T      : latest date to include (inclusive)

    Returns
    -------
    DataFrame with columns:
      [symbol, bb_middle, bb_upper, bb_lower, bb_pct_b,
       bb_bandwidth_curr_wk, bb_bandwidth_prev_wk,
       bb_bandwidth_prev_2wk, bb_bandwidth_prev_3wk, bb_squeeze]
    """
    df = prices[prices["date"] <= T][["symbol", "date", "close"]].copy()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    records = []
    for symbol, grp in df.groupby("symbol", sort=False):
        row = _compute_bb(grp["close"])
        row["symbol"] = symbol
        records.append(row)

    results = pd.DataFrame(records)

    for col in ["bb_middle", "bb_pct_b", "bb_bandwidth_curr_wk"]:
        n_null = results[col].isnull().sum()
        if n_null > 0:
            print(f"WARNING: {n_null} symbol(s) have NaN {col} (< {BB_PERIOD} price rows or zero std)")

    valid_pct = results["bb_pct_b"].dropna()
    valid_bw = results["bb_bandwidth_curr_wk"].dropna()
    if len(valid_pct):
        print(f"bb_pct_b            : [{valid_pct.min():.4f}, {valid_pct.max():.4f}]")
    if len(valid_bw):
        print(f"bb_bandwidth_curr_wk: [{valid_bw.min():.4f}, {valid_bw.max():.4f}]")

    squeeze_counts = results["bb_squeeze"].value_counts(dropna=False).to_dict()
    print(f"bb_squeeze counts   : {squeeze_counts}")

    return results[
        [
            "symbol",
            "bb_middle",
            "bb_upper",
            "bb_lower",
            "bb_pct_b",
            "bb_bandwidth_curr_wk",
            "bb_bandwidth_prev_wk",
            "bb_bandwidth_prev_2wk",
            "bb_bandwidth_prev_3wk",
            "bb_squeeze",
        ]
    ]
