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


"""Run an event study: announcements x validated bars -> CAR + significance.

Market proxy is the equal-weight mean return of the validated universe
(falls back to the event instrument itself if it is the only one).

Usage:
    python scripts/event_study.py --symbol RELIANCE --pre 5 --post 20
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.research import EventStudyResult, event_study
from indian_quant.storage import MetadataStore, ParquetStore


def load_returns(store: ParquetStore, symbol: str) -> pd.Series:
    df = store.read_bars(layer="validated", exchange="NSE", symbol=symbol)
    series = pd.Series(
        df["close"].values,
        index=pd.to_datetime(df["timestamp"], utc=True),
    ).sort_index()
    return series.pct_change().dropna()


def main() -> int:
    parser = argparse.ArgumentParser(description="Announcement event study")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--pre", type=int, default=5)
    parser.add_argument("--post", type=int, default=20)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    symbol = args.symbol.upper()
    store = ParquetStore(settings.data_root, settings.storage.parquet_compression)

    adf = store.read_frame(layer="normalized", dataset="announcements", exchange="NSE", name=symbol)
    returns = load_returns(store, symbol)

    universe = sorted((settings.normalized_dir / "bars_1d" / "NSE").glob("*.parquet"))
    market_frames = []
    for path in universe:
        try:
            mdf = store.read_bars(layer="validated", exchange="NSE", symbol=path.stem)
        except FileNotFoundError:
            continue
        market_frames.append(
            pd.Series(
                mdf["close"].values,
                index=pd.to_datetime(mdf["timestamp"], utc=True),
            ).pct_change()
        )
    if len(market_frames) > 1:
        market_returns = pd.concat(market_frames, axis=1).mean(axis=1).dropna()
        benchmark = f"equal-weight mean of {len(market_frames)} instruments"
    else:
        market_returns = pd.Series(0.0, index=returns.index)
        benchmark = "zero (single-instrument universe)"

    events = pd.DatetimeIndex(pd.to_datetime(adf["published_at"], utc=True)).sort_values()
    result: EventStudyResult = event_study(returns, market_returns, events, pre=args.pre, post=args.post)

    report = {
        "symbol": symbol,
        "n_announcements": len(adf),
        "window": list(result.window),
        "benchmark": benchmark,
        "n_events_in_sample": result.n_events,
        "mean_car": round(result.mean_car, 6) if result.mean_car == result.mean_car else None,
        "median_car": round(result.median_car, 6) if result.median_car == result.median_car else None,
        "t_stat": round(result.t_stat, 3) if result.t_stat == result.t_stat else None,
        "p_value": round(result.p_value, 4) if result.p_value == result.p_value else None,
    }
    print(json.dumps(report, indent=2))

    metadata = MetadataStore(settings.storage.metadata_dsn)
    metadata.record_run(
        f"event-study-{symbol}-{int(events[0].timestamp())}",
        kind="event_study",
        config_hash=f"{args.pre}-{args.post}",
        metrics={k: v for k, v in report.items() if isinstance(v, (int, float)) or v is None},
    )
    metadata.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
