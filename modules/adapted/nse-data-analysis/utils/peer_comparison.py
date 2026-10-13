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
peer_comparison.py
===================
Sector/industry relative comparison. Once the universe is fetched, this computes
sector median multiples (used by valuation.py for relative valuation) and ranks
each stock against same-sector peers on key metrics.
"""


import pandas as pd


def compute_sector_medians(df: pd.DataFrame) -> pd.DataFrame:
    """
    df must contain columns: Sector, PE, PB (at minimum).
    Returns a DataFrame indexed by Sector with median PE / PB / ROE / Margin.
    """
    if df.empty or "Sector" not in df.columns:
        return pd.DataFrame()

    agg_cols = {}
    for col, out_name in [
        ("PE", "Sector Median PE"),
        ("PB", "Sector Median PB"),
        ("ROE %", "Sector Median ROE %"),
        ("Profit Margin %", "Sector Median Margin %"),
    ]:
        if col in df.columns:
            agg_cols[out_name] = df.groupby("Sector")[col].median()

    if not agg_cols:
        return pd.DataFrame()

    return pd.DataFrame(agg_cols)


def attach_peer_context(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds sector-relative rank columns: how this stock's PE/PB/ROE compares to
    same-sector peers, expressed as a percentile (0-100, higher = more favorable
    for ROE/Margin, lower percentile = cheaper for PE/PB).
    """
    if df.empty or "Sector" not in df.columns:
        return df

    df = df.copy()

    if "PE" in df.columns:
        df["PE Percentile (vs Sector)"] = df.groupby("Sector")["PE"].rank(pct=True) * 100

    if "ROE %" in df.columns:
        df["ROE Percentile (vs Sector)"] = df.groupby("Sector")["ROE %"].rank(pct=True) * 100

    if "Score" in df.columns:
        df["Score Rank (vs Sector)"] = df.groupby("Sector")["Score"].rank(
            ascending=False, method="min"
        )

    return df


def get_sector_median(df: pd.DataFrame, sector: str, metric: str) -> float | None:
    """Quick lookup used by valuation.py's relative_valuation for a single stock."""
    if df.empty or sector is None:
        return None
    subset = df[df["Sector"] == sector]
    if subset.empty or metric not in subset.columns:
        return None
    val = subset[metric].median()
    return float(val) if pd.notna(val) else None
