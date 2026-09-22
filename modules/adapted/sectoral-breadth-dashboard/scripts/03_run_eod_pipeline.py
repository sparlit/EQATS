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


# scripts/03_run_eod_pipeline.py
# GitHub Actions EOD orchestration. All calculations and display-file creation
# happen here; Streamlit later reads only finished date snapshots.


import subprocess
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def run(script_name: str) -> None:
    script_path = ROOT / "scripts" / script_name
    if not script_path.exists():
        msg = f"Pipeline script missing: {script_path}"
        raise FileNotFoundError(msg)
    print(f"\n========== RUNNING {script_name} ==========")
    subprocess.run([sys.executable, str(script_path)], check=True)


def validate_outputs() -> None:
    required_files = [
        PROCESSED / "stock_daily_features.parquet",
        PROCESSED / "basic_industry_daily_features.parquet",
        PROCESSED / "industry_daily_features.parquet",
        PROCESSED / "sector_daily_features.parquet",
        PROCESSED / "dashboard_basic_industry_history.parquet",
        PROCESSED / "dashboard_industry_history.parquet",
        PROCESSED / "dashboard_sector_history.parquet",
        PROCESSED / "dashboard_stock_history.parquet",
        PROCESSED / "dashboard_dates.parquet",
        PROCESSED / "dashboard_snapshots",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]
    if missing:
        raise FileNotFoundError("EOD pipeline did not produce required outputs:\n" + "\n".join(missing))

    dates = pd.read_parquet(PROCESSED / "dashboard_dates.parquet")
    if dates.empty or "date" not in dates.columns:
        msg = "dashboard_dates.parquet is empty or missing the date column"
        raise ValueError(msg)
    dates["date"] = pd.to_datetime(dates["date"], errors="coerce")
    dates = dates.dropna(subset=["date"])
    if dates.empty:
        msg = "dashboard_dates.parquet contains no valid dates"
        raise ValueError(msg)

    latest = dates["date"].max().strftime("%Y-%m-%d")
    latest_snapshot = PROCESSED / "dashboard_snapshots" / latest
    expected_snapshot_files = [
        latest_snapshot / "basic_industry_snapshot.parquet",
        latest_snapshot / "industry_snapshot.parquet",
        latest_snapshot / "stock_snapshot.parquet",
        latest_snapshot / "top_buy_candidates.parquet",
        latest_snapshot / "ipo_watchlist.parquet",
        latest_snapshot / "metadata.json",
    ]
    absent = [str(path.relative_to(ROOT)) for path in expected_snapshot_files if not path.exists()]
    if absent:
        raise FileNotFoundError("Latest date snapshot is incomplete:\n" + "\n".join(absent))

    basic = pd.read_parquet(latest_snapshot / "basic_industry_snapshot.parquet")
    stock = pd.read_parquet(latest_snapshot / "stock_snapshot.parquet")
    if basic.empty:
        msg = f"Latest Basic Industry snapshot is empty: {latest}"
        raise ValueError(msg)
    if stock.empty:
        msg = f"Latest stock snapshot is empty: {latest}"
        raise ValueError(msg)

    print("========== OUTPUT VALIDATION PASSED ==========")
    print(f"Available dashboard dates: {len(dates):,}")
    print(f"Latest snapshot: {latest}")
    print(f"Latest Basic Industry rows: {len(basic):,}")
    print(f"Latest stock rows: {len(stock):,}")


def main() -> None:
    print("========== EOD PIPELINE START ==========")
    # Classification/universe refresh is intentionally handled by dedicated
    # workflows before this EOD workflow. This pipeline uses the verified,
    # classified master they have published.
    run("01_build_group_features.py")
    run("12_build_dashboard_history.py")
    run("13_build_dashboard_stock_history.py")
    run("02_build_dashboard_tables.py")
    validate_outputs()

    sync_path = PROCESSED / "last_sync.txt"
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sync_path.write_text(timestamp, encoding="utf-8")

    print("========== EOD PIPELINE COMPLETE ==========")
    print(f"Last sync written: {sync_path}")
    print(f"Timestamp UTC: {timestamp}")


if __name__ == "__main__":
    main()
