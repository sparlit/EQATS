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


"""Signal evaluation: forward returns, t-stats, cost-adjusted verdicts."""


from pathlib import Path

import numpy as np
import pandas as pd
from indian_quant.features.delivery import (
    SIGNAL_NAMES,
    add_features,
    prepare_frame,
    signal_mask_with_filters,
)

HORIZONS = (1, 3, 5, 10, 20)
ROUND_TRIP_COST_BPS = 107.0  # measured: 3bps brokerage + 100bps STT sell + stamp


def forward_returns(closes: pd.Series, horizon: int) -> pd.Series:
    """Return series R[t] = close[t+h]/close[t] - 1."""
    out = closes.shift(-horizon) / closes - 1.0
    return out.dropna()


def summarize(events: np.ndarray) -> dict:
    """Distribution stats for one signal x horizon bucket."""
    events = events[~np.isnan(events)]
    n = len(events)
    if n == 0:
        return {"n": 0}
    mean = float(np.mean(events))
    std = float(np.std(events, ddof=1)) if n > 1 else float("nan")
    t_stat = mean / (std / np.sqrt(n)) if n >= 30 and std and not np.isnan(std) else float("nan")
    return {
        "n": n,
        "mean_bps": round(mean * 10_000, 2),
        "median_bps": round(float(np.median(events)) * 10_000, 2),
        "hit_rate": round(float((events > 0).mean()), 4),
        "t_stat": round(t_stat, 3) if not np.isnan(t_stat) else None,
        "net_mean_bps": round(mean * 10_000 - ROUND_TRIP_COST_BPS, 2),
    }


def stability_split(values: np.ndarray) -> tuple[dict, dict]:
    """First-half vs second-half means - naive walk-forward honesty check."""
    half = max(1, len(values) // 2)
    return summarize(values[:half]), summarize(values[half:])


def apply_conditions(frame: pd.DataFrame, conditions: dict) -> pd.Series:
    """Compose a boolean context mask from simple filter conditions."""
    out = pd.Series(True, index=frame.index)
    if "price_max" in conditions:
        out &= frame["close"] <= float(conditions["price_max"])
    if "price_min" in conditions:
        out &= frame["close"] >= float(conditions["price_min"])
    if "volz_min" in conditions:
        out &= frame.get("vol_z", pd.Series(np.nan, index=frame.index)) >= float(conditions["volz_min"])
    if "segment" in conditions:
        out &= frame["segment"] == str(conditions["segment"])
    return out


def evaluate_bucket(
    frames: list[pd.DataFrame],
    signal_name: str,
    horizons: tuple[int, ...] = HORIZONS,
    *,
    cluster_entries: bool = False,
    conditions: dict | None = None,
    rsi_min: float = 30.0,
    rsi_max: float = 70.0,
    require_macd: bool = True,
    require_ma: bool = True,
) -> dict:
    """Aggregate one signal across many prepared symbol frames.

    cluster_entries=True fires only on the first day of each consecutive
    run of the (conditioned) mask - the cost-amortisation view.
    """
    if signal_name not in SIGNAL_NAMES:
        msg = f"unknown signal: {signal_name}"
        raise KeyError(msg)
    conditions = conditions or {}

    buckets: dict[int, list[np.ndarray]] = {h: [] for h in horizons}
    segment_buckets: dict[tuple[str, int], list[np.ndarray]] = {}

    for frame in frames:
        mask = signal_mask_with_filters(
            frame,
            signal_name,
            rsi_min=30.0,
            rsi_max=70.0,
            require_macd=True,
            require_ma=True,
        )
        if conditions:
            mask = mask & apply_conditions(frame, conditions)
        if cluster_entries:
            from indian_quant.features.delivery import cluster_entry_mask

            mask = cluster_entry_mask(mask)
        fired_idx = frame.index[mask]
        if not fired_idx.any():
            continue
        segment = str(frame["segment"].iloc[-1])
        for h in horizons:
            fwd = forward_returns(frame["close"], h)
            vals = fwd.reindex(fired_idx).dropna().to_numpy()
            if len(vals):
                buckets[h].append(vals)
                segment_buckets.setdefault((segment, h), []).append(vals)

    result: dict[str, dict] = {}
    for h in horizons:
        if not buckets[h]:
            continue
        all_vals = np.concatenate(buckets[h])
        stats = summarize(all_vals)
        first, second = stability_split(all_vals)
        stats["first_half"] = {k: first.get(k) for k in ("n", "mean_bps")}
        stats["second_half"] = {k: second.get(k) for k in ("n", "mean_bps")}

        seg_stats: dict[str, dict] = {}
        for segment in ("EQ", "SME"):
            parts = segment_buckets.get((segment, h))
            if parts:
                merged = np.concatenate(parts)
                seg_stats[segment] = summarize(merged)
        if seg_stats:
            stats["by_segment"] = seg_stats

        result[str(h)] = stats
    return result


def prepare_universe(delivery_dir: Path, *, min_rows: int = 40) -> list[pd.DataFrame]:
    """Load every delivery parquet into feature-enriched frames."""
    frames: list[pd.DataFrame] = []
    for path in sorted(Path(delivery_dir).glob("*.parquet")):
        raw = pd.read_parquet(path)
        prepared = prepare_frame(raw, min_rows=min_rows)
        if prepared is None or "segment" not in prepared.columns:
            continue
        frames.append(add_features(prepared))
    return frames


__all__ = [
    "HORIZONS",
    "ROUND_TRIP_COST_BPS",
    "evaluate_bucket",
    "forward_returns",
    "prepare_universe",
    "stability_split",
    "summarize",
]
