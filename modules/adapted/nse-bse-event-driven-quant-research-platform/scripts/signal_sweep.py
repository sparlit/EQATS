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


"""Delivery-percentage anomaly sweep across the full universe.

Loads every symbol's delivery lake file, fires each registered signal,
measures forward returns at multiple horizons net of measured costs,
splits EQ vs SME, checks first/second-half stability, registers the
experiment and writes a ranked JSON + markdown summary.

Usage:
    python scripts/signal_sweep.py [--min-rows 40]
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.features.delivery import SIGNAL_NAMES
from indian_quant.research import ExperimentTracker, signals
from indian_quant.storage import MetadataStore


def rank_table(results: dict[str, dict]) -> list[dict]:
    rows = []
    for signal, by_h in results.items():
        for horizon, stats in by_h.items():
            rows.append(
                {
                    "signal": signal,
                    "horizon": int(horizon),
                    **{
                        k: stats.get(k)
                        for k in ("n", "mean_bps", "net_mean_bps", "hit_rate", "t_stat")
                    },
                    "eq_mean_bps": (stats.get("by_segment", {}).get("EQ", {}) or {}).get(
                        "mean_bps"
                    ),
                    "sme_mean_bps": (stats.get("by_segment", {}).get("SME", {}) or {}).get(
                        "mean_bps"
                    ),
                }
            )
    return sorted(rows, key=lambda r: (r["t_stat"] is None, -(r["t_stat"] or 0)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Delivery signal sweep")
    parser.add_argument("--min-rows", type=int, default=40)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    delivery_dir = settings.normalized_dir / "delivery" / "NSE"
    print(f"loading universe frames from {delivery_dir} ...")
    frames = signals.prepare_universe(delivery_dir, min_rows=args.min_rows)
    total_rows = sum(len(f) for f in frames)
    print(f"usable symbols: {len(frames)} | total rows: {total_rows:,}")

    results: dict[str, dict] = {}
    for name in SIGNAL_NAMES:
        results[name] = signals.evaluate_bucket(frames, name)
        fired = sum(v["n"] for v in results[name].values() if v.get("n"))
        print(f"  {name}: {fired} events evaluated")

    ranked = rank_table(results)

    metadata = MetadataStore(settings.storage.metadata_dsn)
    tracker = ExperimentTracker(metadata)
    run_id = tracker.record(
        kind="signal_sweep_delivery",
        config={
            "min_rows": args.min_rows,
            "signals": list(SIGNAL_NAMES),
            "horizons": list(signals.HORIZONS),
            "cost_bps": signals.ROUND_TRIP_COST_BPS,
        },
        metrics={"n_buckets": len(ranked), "top_t_stat": ranked[0]["t_stat"] if ranked else None},
    )
    metadata.close()
    print(f"experiment registered: {run_id}")

    out_dir = Path("docs/research/generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "delivery_sweep.json").write_text(
        json.dumps({"run_id": run_id, "ranked": ranked, "full": results}, indent=2)
    )

    top = "\n".join(
        f"| {r['signal']} | {r['horizon']}d | {r['n']:,} | {r['mean_bps']} | "
        f"{r['net_mean_bps']} | {r['hit_rate']} | {r['t_stat']} |"
        for r in ranked[:15]
    )
    markdown = (
        "# Delivery sweep — generated summary\n\n"
        f"run_id `{run_id}` · usable symbols {len(frames)} · rows {total_rows:,}\n\n"
        "| signal | h | n | gross bps | NET bps | hit | t |\n|---|---|---|---|---|---|---|\n"
        + top
        + "\n\n(net = gross − 107bps round trip)\n"
    )
    (out_dir / "delivery_sweep_summary.md").write_text(markdown)
    print(markdown[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
