"""
AXIOM Footprint / Order-Flow Analytics — APPROXIMATED.

IMPORTANT — DATA LIMITATION:
A *true* footprint chart needs tick-by-tick trades classified by aggressor
(buy = lifted ask, sell = hit bid). yfinance does not expose that. So this module builds an **approximated** footprint from
1-minute OHLCV bars:

  1. Each 1-min bar's volume is spread across price bins between its low and high.
  2. Buy vs sell split is estimated with a tick/close-position rule:
       - bar up vs previous close  -> bias volume to BUY
       - bar down vs previous close-> bias volume to SELL
       - intra-bar weighting uses close position within the bar's range.

Outputs per price bin: buy_vol, sell_vol, total_vol, delta (buy-sell).
POC = price bin with the greatest total volume.

Upgrade path to TRUE footprint: capture a live tick feed and classify each
print by the prevailing bid/ask, then bucket by price.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger


APPROXIMATION_NOTE = (
    "Approximated from 1-min OHLCV (no tick data). Buy/sell split estimated via "
    "close-position + tick rule — directional read only, not true order flow."
)


@dataclass
class FootprintResult:
    symbol:    str
    profile:   pd.DataFrame      # index=price_bin, cols: buy_vol, sell_vol, total_vol, delta
    poc:       float             # point of control (price of max volume)
    total_delta: float           # net buy-sell over the window
    bins:      int
    bars:      int
    approximated: bool = True


def fetch_intraday(symbol: str, days: int = 1, interval: str = "1m") -> pd.DataFrame:
    """Fetch recent intraday OHLCV bars via yfinance (1m history is ~7 days max)."""
    try:
        df = yf.Ticker(symbol).history(period=f"{days}d", interval=interval)
        if df.empty:
            return df
        df.columns = [c.lower() for c in df.columns]
        if hasattr(df.index, "tzinfo") and df.index.tzinfo:
            df.index = df.index.tz_localize(None)
        return df.dropna(subset=["open", "high", "low", "close", "volume"])
    except Exception as exc:
        logger.debug("intraday fetch failed for {}: {}", symbol, exc)
        return pd.DataFrame()


def _bar_buy_fraction(row: pd.Series, prev_close: float) -> float:
    """
    Estimate the fraction of a bar's volume that was buyer-initiated.
    Combines bar direction (vs prev close) with close position in range.
    Returns a value in [0.15, 0.85] to avoid implausible 0/100 splits.
    """
    rng = row["high"] - row["low"]
    if rng <= 0:
        pos = 0.5
    else:
        pos = (row["close"] - row["low"]) / rng    # 1 = closed on high
    # Direction nudge vs previous close
    if not np.isnan(prev_close):
        if row["close"] > prev_close:
            pos = 0.6 * pos + 0.4 * 0.75
        elif row["close"] < prev_close:
            pos = 0.6 * pos + 0.4 * 0.25
    return float(np.clip(pos, 0.15, 0.85))


def build_footprint(df: pd.DataFrame, symbol: str = "", bins: int = 30) -> FootprintResult:
    """
    Build an approximated footprint volume profile from intraday OHLCV bars.

    Each bar's volume is distributed across price bins it spans; the buy/sell
    split is estimated per bar and applied to every bin the bar touches.
    """
    if df is None or df.empty:
        return FootprintResult(symbol, pd.DataFrame(), 0.0, 0.0, 0, 0)

    lo = float(df["low"].min())
    hi = float(df["high"].max())
    if hi <= lo:
        hi = lo + 1e-6
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2

    buy = np.zeros(bins)
    sell = np.zeros(bins)

    prev_close = np.nan
    for _, row in df.iterrows():
        b_lo, b_hi = row["low"], row["high"]
        vol = float(row["volume"])
        if vol <= 0:
            prev_close = row["close"]
            continue
        # Bins this bar spans
        mask = (edges[1:] > b_lo) & (edges[:-1] < b_hi)
        n_bins = int(mask.sum())
        if n_bins == 0:
            # bar fits in a single bin
            idx = int(np.clip(np.searchsorted(edges, row["close"]) - 1, 0, bins - 1))
            mask = np.zeros(bins, dtype=bool)
            mask[idx] = True
            n_bins = 1
        buy_frac = _bar_buy_fraction(row, prev_close)
        per_bin = vol / n_bins
        buy[mask] += per_bin * buy_frac
        sell[mask] += per_bin * (1 - buy_frac)
        prev_close = row["close"]

    total = buy + sell
    profile = pd.DataFrame({
        "price":     np.round(centers, 2),
        "buy_vol":   np.round(buy, 0),
        "sell_vol":  np.round(sell, 0),
        "total_vol": np.round(total, 0),
        "delta":     np.round(buy - sell, 0),
    })
    poc = float(centers[int(np.argmax(total))]) if total.sum() > 0 else 0.0
    return FootprintResult(
        symbol=symbol,
        profile=profile,
        poc=round(poc, 2),
        total_delta=round(float((buy - sell).sum()), 0),
        bins=bins,
        bars=len(df),
    )
