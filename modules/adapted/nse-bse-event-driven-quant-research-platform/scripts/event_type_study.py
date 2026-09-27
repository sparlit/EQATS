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


"""R3 full study: pooled event-type CAR table across the announcements lake.

For every symbol with both announcements and bars:
    - classify each announcement into an event type
    - keep the FIRST announcement per (symbol, day, type) to avoid duplicates
    - measure CAR [-2, +10] trading days around each event vs zero benchmark
Pools everything by type; reports n / mean CAR bps / t-stat / hit rate.

Usage:
    python scripts/event_type_study.py [--pre 2 --post 10]
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
from indian_quant.research import event_study
from indian_quant.research.event_types import EVENT_TYPES, classify_frame


def symbol_returns(bar_dir: Path, symbol: str) -> pd.Series | None:
    path = bar_dir / f"{symbol}.parquet"
    if not path.exists():
        return None
    bdf = pd.read_parquet(path, columns=["timestamp", "close"])
    closes = pd.Series(
        bdf["close"].values,
        index=pd.DatetimeIndex(pd.to_datetime(bdf["timestamp"], utc=True)),
    ).sort_index()
    return closes.pct_change().dropna()


def main() -> int:
    parser = argparse.ArgumentParser(description="Event-type CAR study")
    parser.add_argument("--pre", type=int, default=2)
    parser.add_argument("--post", type=int, default=10)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    ann_dir = settings.normalized_dir / "announcements" / "NSE"
    bar_dir = settings.normalized_dir / "bars_1d" / "NSE"

    per_type_values: dict[str, list[np.ndarray]] = {t: [] for t in EVENT_TYPES}
    symbols_studied = 0
    events_studied = 0

    for ann_path in sorted(ann_dir.glob("*.parquet")):
        if ann_path.stem.startswith("_"):
            continue
        symbol = ann_path.stem
        ret = symbol_returns(bar_dir, symbol)
        if ret is None or len(ret) < 60:
            continue
        ann = pd.read_parquet(ann_path)
        text_col = next((c for c in ("headline", "category", "desc") if c in ann.columns), None)
        if text_col is None or ann.empty:
            continue
        ann = classify_frame(ann.drop_duplicates(subset=["published_at"]), text_col)

        for event_type in EVENT_TYPES:
            subset = ann[ann["event_type"] == event_type]
            if subset.empty:
                continue
            es = event_study(
                ret,
                pd.Series(0.0, index=ret.index),
                pd.DatetimeIndex(pd.to_datetime(subset["published_at"], utc=True)).sort_values(),
                pre=args.pre,
                post=args.post,
            )
            if es.n_events and es.cars is not None and len(es.cars):
                per_type_values[event_type].append(np.asarray(es.cars, dtype=float))
                events_studied += es.n_events
        symbols_studied += 1

    rows = []
    for event_type in EVENT_TYPES:
        vals = per_type_values[event_type]
        if not vals:
            continue
        merged = np.concatenate(vals)
        merged = merged[~np.isnan(merged)]
        if len(merged) < 30:
            continue
        mean_bps = float(np.mean(merged)) * 10_000
        std = float(np.std(merged, ddof=1))
        t = mean_bps / 10_000 / (std / np.sqrt(len(merged))) if std else float("nan")
        rows.append(
            {
                "event_type": event_type,
                "n_events": len(merged),
                "mean_car_bps": round(mean_bps, 1),
                "hit_rate": round(float((merged > 0).mean()), 3),
                "t_stat_pooled": round(t, 2),
            }
        )

    table = pd.DataFrame(rows).sort_values("t_stat_pooled", ascending=False)
    print(f"symbols studied: {symbols_studied} | events: {events_studied:,} ")
    if not table.empty:
        print(table.to_string(index=False))

    out_dir = Path("docs/research/generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": datetime.now(UTC).isoformat(),
        "symbols": symbols_studied,
        "events": events_studied,
        "window": [args.pre, args.post],
        "table": table.to_dict(orient="records"),
    }
    (out_dir / "event_type_car.json").write_text(json.dumps(payload, indent=1))
    print(f"saved -> {out_dir / 'event_type_car.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
