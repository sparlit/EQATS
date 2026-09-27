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


"""SME-focused dz_hi_up signal study: 5-day hold, no stop, EQ baseline comparison.

Tests: high delivery on up-move in SME stocks -> forward return over 5 days.
Compares against EQ universe and random-entry control.

Usage:
    python scripts/sme_dz_hi_up_study.py [--horizon 5] [--min-rows 40]
"""


import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from indian_quant.config import load_settings
from indian_quant.features.delivery import add_features, prepare_frame, signal_mask
from indian_quant.research import ExperimentTracker
from indian_quant.storage import MetadataStore

HORIZON = 5


def load_sme_frames(settings) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    """Load delivery frames split into SME and EQ groups."""
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    sme_frames: list[pd.DataFrame] = []
    eq_frames: list[pd.DataFrame] = []
    for path in sorted(dl_dir.glob("*.parquet")):
        raw = pd.read_parquet(path)
        frame = prepare_frame(raw, min_rows=40)
        if frame is None or "segment" not in frame.columns:
            continue
        frame = add_features(frame)
        seg = str(frame["segment"].iloc[-1])
        if seg == "SME":
            sme_frames.append(frame)
        elif seg == "EQ":
            eq_frames.append(frame)
    return sme_frames, eq_frames


def evaluate_signal(frames: list[pd.DataFrame], signal_name: str, horizon: int) -> dict:
    """Evaluate signal across frames; returns aggregated stats."""
    all_rets: list[float] = []
    per_symbol: list[dict] = []

    for frame in frames:
        mask = signal_mask(frame, signal_name)
        fired_idx = frame.index[mask]
        if not fired_idx.any():
            continue

        closes = frame["close"].reset_index(drop=True)
        fwd = closes.shift(-horizon) / closes - 1.0

        # one position per symbol: take first firing only per cluster
        cluster_first = mask & ~mask.shift(fill_value=False)

        for idx in frame.index[cluster_first]:
            pos = frame.index.get_loc(idx)
            fr = fwd.iloc[pos]
            if pd.isna(fr):
                continue
            all_rets.append(float(fr))
            per_symbol.append(
                {
                    "symbol": str(frame["symbol"].iloc[-1]),
                    "date": str(frame.loc[idx, "date"])[:10],
                    "entry_close": float(frame.loc[idx, "close"]),
                    "fwd_ret_bps": round(float(fr) * 10_000, 1),
                }
            )

    vals = np.array(all_rets)
    n = len(vals)
    if n == 0:
        return {"n": 0}

    mean_bps = float(np.mean(vals)) * 10_000
    std = float(np.std(vals, ddof=1))
    t_stat = mean_bps / 10_000 / (std / np.sqrt(n)) if std > 0 else None
    half = max(1, n // 2)
    sorted_vals = sorted(per_symbol, key=lambda x: x["date"])

    return {
        "n_trades": n,
        "mean_gross_bps": round(mean_bps, 1),
        "median_bps": round(float(np.median(vals)) * 10_000, 1),
        "win_rate": round(float((vals > 0).mean()), 3),
        "t_stat": round(t_stat, 2) if t_stat else None,
        "std_bps": round(std * 10_000, 1),
        "best_trade_bps": round(float(np.max(vals)) * 10_000, 1),
        "worst_trade_bps": round(float(np.min(vals)) * 10_000, 1),
        "first_half_mean_bps": round(float(np.mean(list(vals[:half]))) * 10_000, 1) if half > 0 else None,
        "second_half_mean_bps": round(float(np.mean(list(vals[half:]))) * 10_000, 1) if len(vals[half:]) > 0 else None,
        "per_symbol": sorted_symbols(sorted_vals),
    }


def sorted_symbols(rows: list[dict]) -> list[dict]:
    from collections import defaultdict

    by_sym: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r["fwd_ret_bps"])
    out = []
    for sym, rets in sorted(by_sym.items(), key=lambda x: -len(x[1])):
        out.append(
            {
                "symbol": sym,
                "n_signals": len(rets),
                "mean_bps": round(float(np.mean(rets)), 1),
                "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets), 3),
            }
        )
    return out


def random_baseline(frames: list[pd.DataFrame], horizon: int, n_signals: int, seed: int = 42) -> dict:
    """Control group: random entries with same horizon."""
    rng = np.random.default_rng(seed)
    all_vals = []
    for frame in frames:
        closes = frame["close"].reset_index(drop=True)
        fwd = closes.shift(-horizon) / closes - 1.0
        valid = fwd.dropna()
        if len(valid) < 5:
            continue
        sample_n = min(n_signals // max(1, len(frames)), len(valid))
        if sample_n < 1:
            continue
        idx = rng.choice(valid.index, size=sample_n, replace=False)
        all_vals.extend(valid.loc[idx].tolist())
    vals = np.array(all_vals)
    if len(vals) == 0:
        return {"n": 0}
    return {
        "n_random": len(vals),
        "mean_bps": round(float(np.mean(vals)) * 10_000, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SME dz_hi_up 5d study")
    parser.add_argument("--min-rows", type=int, default=40)
    parser.parse_args()

    settings = load_settings()

    print("loading delivery lake ...")
    sme_frames, eq_frames = load_sme_frames(settings)
    print(f"SME symbols: {len(sme_frames)} | EQ symbols: {len(eq_frames)}")

    print("\n=== SME: dz_hi_up, 5-day hold, no stop ===")
    sme_result = evaluate_signal(sme_frames, "dz_hi_up", HORIZON)
    print(json.dumps({k: v for k, v in sme_result.items() if k != "per_symbol"}, indent=2))

    print("\n=== EQ BASELINE: dz_hi_up, 5-day hold ===")
    eq_result = evaluate_signal(eq_frames, "dz_hi_up", HORIZON)
    print(json.dumps({k: v for k, v in eq_result.items() if k != "per_symbol"}, indent=2))

    print("\n=== RANDOM CONTROL (same n as SME) ===")
    ctrl = random_baseline(eq_frames, HORIZON, sme_result.get("n_trades", 100))
    print(json.dumps(ctrl, indent=1))

    # register experiment
    metadata = MetadataStore(settings.storage.metadata_dsn)
    tracker = ExperimentTracker(metadata)
    run_id = tracker.record(
        kind="sme_dz_hi_up_5d",
        config={"signal": "dz_hi_up", "horizon": HORIZON, "universe": "SME", "stop": None},
        metrics={
            "n_trades": sme_result.get("n_trades", 0),
            "mean_bps": sme_result.get("mean_gross_bps"),
            "eq_mean_bps": eq_result.get("mean_gross_bps"),
        },
    )
    metadata.close()

    # save results
    out_dir = Path("docs/research/generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "generated": datetime.now(UTC).isoformat(),
        "signal": "dz_hi_up",
        "horizon_days": HORIZON,
        "stop": None,
        "sme": {k: v for k, v in sme_result.items() if k != "per_symbol"},
        "sme_top_symbols": sme_result.get("per_symbol", [])[:20],
        "eq_baseline": {k: v for k, v in eq_result.items() if k != "per_symbol"},
        "random_control": ctrl,
    }
    (out_dir / "sme_dz_hi_up_5d.json").write_text(json.dumps(payload, indent=1))
    print(f"\nsaved -> {out_dir / 'sme_dz_hi_up_5d.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
