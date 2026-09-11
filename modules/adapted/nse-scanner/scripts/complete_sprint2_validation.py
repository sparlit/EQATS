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


"""Restore repository market snapshots and complete Sprint 2 validation.

Safe for CI: creates a temporary SQLite database, never sends Telegram messages,
and writes only JSON/CSV outputs under output/v2_validation.
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from nse_loader import init_database
from nse_market_store import restore_prices, snapshot_dates
from v2.database import V2Database
from v2.indicators import atr, hybrid_hull, relative_strength_return
from v2.snapshots import build_market_snapshot, persist_market_snapshot


def _equal_weight_benchmark(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices[["symbol", "trade_date", "close"]].copy()
    frame["return"] = frame.groupby("symbol")["close"].pct_change()
    daily = frame.groupby("trade_date", as_index=False)["return"].mean().fillna(0.0)
    daily["close"] = (1.0 + daily["return"]).cumprod() * 1000.0
    return daily[["trade_date", "close"]]


def run(db_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    init_database(str(db_path))
    restored = restore_prices(db_path, min_days=1)
    dates = snapshot_dates()

    market = V2Database(db_path)
    prices = market.load_prices(min_sessions=55)
    if prices.empty:
        msg = "No usable market prices were restored"
        raise RuntimeError(msg)

    indices = market.load_indices()
    benchmark_source = "INDEX_PERF"
    if indices.empty:
        benchmark = _equal_weight_benchmark(prices)
        benchmark_source = "EQUAL_WEIGHT_UNIVERSE_FALLBACK"
    else:
        counts = indices.groupby("index_name")["trade_date"].nunique().sort_values(ascending=False)
        benchmark_name = counts.index[0]
        benchmark = indices[indices["index_name"] == benchmark_name][["trade_date", "close"]]
        benchmark_source = f"INDEX_PERF:{benchmark_name}"

    snapshot = build_market_snapshot(prices, benchmark)
    snapshot["benchmark_source"] = benchmark_source
    snapshot["sector_history_validated"] = False
    snapshot["sector_validation_note"] = (
        "Sector index history is not persisted in market_data snapshots; sector-relative outputs remain disabled."
    )
    persist_market_snapshot(db_path, snapshot)

    latest_symbol = prices.groupby("symbol").size().sort_values(ascending=False).index[0]
    sample = prices[prices["symbol"] == latest_symbol].sort_values("trade_date").copy()
    hh = hybrid_hull(sample)
    sample_out = {
        "symbol": latest_symbol,
        "sessions": len(sample),
        "latest_atr14": float(atr(sample, 14).iloc[-1]),
        "latest_hybrid_hull_state": int(hh["hybrid_hull_state"].iloc[-1]),
    }

    aligned = sample[["trade_date", "close"]].merge(
        benchmark, on="trade_date", how="inner", suffixes=("_stock", "_benchmark")
    )
    if len(aligned) >= 66:
        rs = relative_strength_return(aligned["close_stock"], aligned["close_benchmark"], lookback=66)
        sample_out["latest_rs66_excess_return"] = float(rs.iloc[-1])

    result = {
        "status": "PASS",
        "restored_sessions": restored,
        "snapshot_count": len(dates),
        "oldest_snapshot": dates[0] if dates else None,
        "newest_snapshot": dates[-1] if dates else None,
        "price_rows": len(prices),
        "symbols": int(prices["symbol"].nunique()),
        "benchmark_source": benchmark_source,
        "market_regime": snapshot,
        "sample_reconciliation": sample_out,
        "sector_history_validated": False,
    }
    (output_dir / "sprint2_validation.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    pd.DataFrame([snapshot]).to_csv(output_dir / "market_regime_snapshot.csv", index=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="output/v2_validation/sprint2.db")
    parser.add_argument("--output", default="output/v2_validation")
    args = parser.parse_args()
    result = run(Path(args.db), Path(args.output))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
