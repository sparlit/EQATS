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


"""Analyze circuit breaker patterns and compute signal scoring weights.

Reads circuit limits + delivery/bars data, identifies circuit hits,
computes forward returns at multiple horizons, and outputs pattern stats
used to tune circuit_breakout hypothesis signal scoring.

Usage:
    python scripts/analyze_circuit_patterns.py
    python scripts/analyze_circuit_patterns.py --days 90
"""


import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config.connections import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

NSE_DELIVERY_DIR = Path("data/normalized/delivery/NSE")
NSE_BARS_DIR = Path("data/normalized/bars_1d/NSE")

HORIZONS = [1, 2, 3, 5, 10, 15]


def load_circuit_limits(engine, start_date: date, end_date: date) -> pd.DataFrame:
    """Load circuit limits from DB."""
    with engine.connect() as conn:
        df = pd.read_sql(
            sa.text("""
            SELECT symbol, trade_date, prev_close, upper_circuit, lower_circuit, filter_pct, source
            FROM stock_circuit_limits
            WHERE trade_date >= :start AND trade_date <= :end
            ORDER BY symbol, trade_date
        """),
            conn,
            params={"start": str(start_date), "end": str(end_date)},
        )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def load_bars(symbol: str, start_date: date, end_date: date) -> pd.DataFrame | None:
    """Load bars for a symbol."""
    path = NSE_BARS_DIR / f"{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if "timestamp" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_delivery(symbol: str, start_date: date, end_date: date) -> pd.DataFrame | None:
    """Load delivery data for a symbol."""
    path = NSE_DELIVERY_DIR / f"{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if "date" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def identify_circuit_hits(circuit_df: pd.DataFrame, bars_df: pd.DataFrame) -> pd.DataFrame:
    """Identify actual circuit hit days by comparing close to limits."""
    if circuit_df.empty or bars_df is None or bars_df.empty:
        return pd.DataFrame()

    # Merge circuit limits with bars
    merged = bars_df.merge(
        circuit_df[["trade_date", "upper_circuit", "lower_circuit", "filter_pct"]],
        left_on="date",
        right_on="trade_date",
        how="inner",
    )
    if merged.empty:
        return pd.DataFrame()

    # Classify circuit hits
    merged["upper_hit"] = merged["close"] >= merged["upper_circuit"] * 0.998
    merged["lower_hit"] = merged["close"] <= merged["lower_circuit"] * 1.002

    # Compute forward returns at multiple horizons
    for h in HORIZONS:
        merged[f"fwd_{h}d"] = merged["close"].shift(-h) / merged["close"] - 1

    # Volume ratio
    if "volume" in merged.columns:
        vol_avg = merged["volume"].rolling(20, min_periods=5).mean()
        merged["vol_ratio"] = merged["volume"] / vol_avg.replace(0, np.nan)
    else:
        merged["vol_ratio"] = 1.0

    # Consecutive upper circuits
    merged["consec_upper"] = 0
    count = 0
    for i in range(len(merged)):
        if merged["upper_hit"].iloc[i]:
            count += 1
            merged.iloc[i, merged.columns.get_loc("consec_upper")] = count
        else:
            count = 0

    # Consecutive lower circuits
    merged["consec_lower"] = 0
    count = 0
    for i in range(len(merged)):
        if merged["lower_hit"].iloc[i]:
            count += 1
            merged.iloc[i, merged.columns.get_loc("consec_lower")] = count
        else:
            count = 0

    # Next-day continuation
    merged["next_open"] = (
        merged["open"].shift(-1) if "open" in merged.columns else merged["close"].shift(-1)
    )
    merged["next_close"] = merged["close"].shift(-1)
    merged["continuation"] = (merged["next_open"] >= merged["close"] * 0.98) & (
        merged["next_close"] >= merged["close"] * 0.97
    )

    return merged


def analyze_patterns(hits: pd.DataFrame) -> dict:
    """Compute pattern statistics from circuit hit data."""
    if hits.empty:
        return {}

    stats = {}

    # Filter % breakdown
    for filt in sorted(hits["filter_pct"].unique()):
        subset = hits[hits["filter_pct"] == filt]
        key = f"filter_{int(filt)}pct"
        stats[key] = {
            "count": int(len(subset)),
            "upper_hits": int(subset["upper_hit"].sum()),
            "lower_hits": int(subset["lower_hit"].sum()),
        }
        for h in HORIZONS:
            col = f"fwd_{h}d"
            if col in subset.columns:
                valid = subset[col].dropna()
                if len(valid) > 0:
                    stats[key][f"avg_fwd_{h}d"] = round(float(valid.mean()) * 100, 2)
                    stats[key][f"win_rate_{h}d"] = round(float((valid > 0).mean()) * 100, 1)

    # Volume ratio buckets
    for vol_lo, vol_hi, label in [
        (0, 1.5, "low"),
        (1.5, 3, "medium"),
        (3, 10, "high"),
        (10, 100, "extreme"),
    ]:
        subset = hits[
            (hits["vol_ratio"] >= vol_lo) & (hits["vol_ratio"] < vol_hi) & hits["upper_hit"]
        ]
        if len(subset) > 0:
            stats[f"vol_{label}"] = {"count": int(len(subset))}
            for h in HORIZONS:
                col = f"fwd_{h}d"
                if col in subset.columns:
                    valid = subset[col].dropna()
                    if len(valid) > 0:
                        stats[f"vol_{label}"][f"avg_fwd_{h}d"] = round(float(valid.mean()) * 100, 2)
                        stats[f"vol_{label}"][f"win_rate_{h}d"] = round(
                            float((valid > 0).mean()) * 100, 1
                        )

    # Consecutive upper circuits
    for n in [1, 2, 3, 4]:
        subset = hits[(hits["consec_upper"] == n) & hits["upper_hit"]]
        if len(subset) > 0:
            stats[f"consec_{n}"] = {"count": int(len(subset))}
            for h in HORIZONS:
                col = f"fwd_{h}d"
                if col in subset.columns:
                    valid = subset[col].dropna()
                    if len(valid) > 0:
                        stats[f"consec_{n}"][f"avg_fwd_{h}d"] = round(float(valid.mean()) * 100, 2)
                        stats[f"consec_{n}"][f"win_rate_{h}d"] = round(
                            float((valid > 0).mean()) * 100, 1
                        )

    # Continuation pattern
    cont = hits[hits["continuation"] & hits["upper_hit"]]
    no_cont = hits[~hits["continuation"] & hits["upper_hit"]]
    if len(cont) > 0:
        stats["with_continuation"] = {"count": int(len(cont))}
        for h in HORIZONS:
            col = f"fwd_{h}d"
            if col in cont.columns:
                valid = cont[col].dropna()
                if len(valid) > 0:
                    stats["with_continuation"][f"avg_fwd_{h}d"] = round(
                        float(valid.mean()) * 100, 2
                    )
                    stats["with_continuation"][f"win_rate_{h}d"] = round(
                        float((valid > 0).mean()) * 100, 1
                    )
    if len(no_cont) > 0:
        stats["no_continuation"] = {"count": int(len(no_cont))}
        for h in HORIZONS:
            col = f"fwd_{h}d"
            if col in no_cont.columns:
                valid = no_cont[col].dropna()
                if len(valid) > 0:
                    stats["no_continuation"][f"avg_fwd_{h}d"] = round(float(valid.mean()) * 100, 2)
                    stats["no_continuation"][f"win_rate_{h}d"] = round(
                        float((valid > 0).mean()) * 100, 1
                    )

    # Lower circuit reversal
    lower_hits = hits[hits["lower_hit"]]
    if len(lower_hits) > 0:
        stats["lower_circuit"] = {"count": int(len(lower_hits))}
        for h in HORIZONS:
            col = f"fwd_{h}d"
            if col in lower_hits.columns:
                valid = lower_hits[col].dropna()
                if len(valid) > 0:
                    stats["lower_circuit"][f"avg_fwd_{h}d"] = round(float(valid.mean()) * 100, 2)
                    stats["lower_circuit"][f"win_rate_{h}d"] = round(
                        float((valid > 0).mean()) * 100, 1
                    )

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze circuit breaker patterns")
    parser.add_argument("--days", type=int, default=180, help="Look back N days")
    args = parser.parse_args()

    engine = get_engine()
    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)

    log.info(f"Loading circuit limits: {start_date} to {end_date}")
    circuit_df = load_circuit_limits(engine, start_date, end_date)
    log.info(f"  {len(circuit_df)} circuit limit records")

    if circuit_df.empty:
        log.error(
            "No circuit limits found. Run ingest_circuit_limits.py or infer_historical_circuits.py first."
        )
        return 1

    # Get unique symbols
    symbols = circuit_df["symbol"].unique().tolist()
    log.info(f"  {len(symbols)} unique symbols")

    # Analyze each stock
    all_hits = []
    for i, sym in enumerate(symbols):
        sym_circuit = circuit_df[circuit_df["symbol"] == sym]
        bars = load_bars(sym, start_date, end_date)
        delivery = load_delivery(sym, start_date, end_date)

        # Use bars if available, otherwise delivery for close prices
        price_df = bars if bars is not None else delivery
        if price_df is None or price_df.empty:
            continue

        hits = identify_circuit_hits(sym_circuit, price_df)
        if not hits.empty:
            hits["symbol"] = sym
            all_hits.append(hits)

        if (i + 1) % 500 == 0:
            log.info(f"  Processed {i + 1}/{len(symbols)} stocks")

    if not all_hits:
        log.error("No circuit hits found")
        return 1

    all_hits_df = pd.concat(all_hits, ignore_index=True)
    upper_count = all_hits_df["upper_hit"].sum()
    lower_count = all_hits_df["lower_hit"].sum()
    log.info(
        f"Circuit hits: {upper_count} upper, {lower_count} lower across {len(all_hits_df)} merged rows"
    )

    # Run analysis
    stats = analyze_patterns(all_hits_df)

    # Save stats
    stats_path = Path("data/cache/circuit_pattern_stats.json")
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    log.info(f"Stats saved to {stats_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("CIRCUIT BREAKER PATTERN ANALYSIS")
    print("=" * 70)
    for key, val in sorted(stats.items()):
        print(f"\n{key}:")
        for k, v in val.items():
            print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
