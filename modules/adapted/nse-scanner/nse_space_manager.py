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
nse_space_manager.py — Intelligent Space Manager
=================================================
"""

import argparse
import contextlib
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    sys.exit(1)

_HERE = Path(__file__).parent

_DATA_DIR_NAME = getattr(config, "NSE_DATA_DIR", None) or getattr(config, "DATA_DIR", "nse_data")
DATA_DIR = _HERE / _DATA_DIR_NAME
OUTPUT_DIR = _HERE / getattr(config, "OUTPUT_DIR", "output")
LOG_DIR = _HERE / getattr(config, "LOG_DIR", "logs")
DB_PATH = _HERE / getattr(config, "DB_PATH", "nse_scanner.db")

KEEP_CSV_DAYS = 7
KEEP_LOG_DAYS = 30
KEEP_EXCEL = 1
KEEP_NEWS_DAYS = 7

NEVER_DELETE = {
    "scan_history.json",
    "telegram_last_scan.json",
    "scan_health.json",
    "nse_scanner.db",
}


def _size_mb(path):
    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_size / 1_048_576
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1_048_576


def _age_days(path):
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days


def show_status():
    print("\n" + "=" * 55 + "\n  NSE SCANNER — DISK USAGE\n" + "=" * 55)
    items = [
        ("SQLite DB", DB_PATH),
        (f"Raw CSVs ({_DATA_DIR_NAME}/)", DATA_DIR),
        ("Excel output", OUTPUT_DIR),
        ("Logs", LOG_DIR),
        ("Pagination JSON", _HERE / "telegram_last_scan.json"),
    ]
    total = 0.0
    for label, path in items:
        size = _size_mb(path)
        total += size
        mark = "✅" if path.exists() else "⚠️ "
        print(f"  {mark}  {label:<28} {size:>7.1f} MB")

    if DATA_DIR.exists():
        csvs = list(DATA_DIR.rglob("*.csv"))
        print(f"\n  CSV files   : {len(csvs)} files")
        if csvs:
            newest = max(csvs, key=lambda f: f.stat().st_mtime)
            oldest = min(csvs, key=lambda f: f.stat().st_mtime)
            print(f"  Newest CSV  : {newest.name}  ({_age_days(newest)}d old)")
            print(f"  Oldest CSV  : {oldest.name}  ({_age_days(oldest)}d old)")
            old_count = sum(1 for f in csvs if _age_days(f) > KEEP_CSV_DAYS)
            if old_count:
                old_mb = sum(f.stat().st_size for f in csvs if _age_days(f) > KEEP_CSV_DAYS) / 1_048_576
                print(f"\n  ⚠️  {old_count} CSVs older than {KEEP_CSV_DAYS} days ({old_mb:.1f}MB)")

    if OUTPUT_DIR.exists():
        xlsx = sorted(OUTPUT_DIR.glob("NSE_Scanner_*.xlsx"), key=lambda f: f.stat().st_mtime, reverse=True)
        if xlsx:
            print(f"\n  Excel files : {len(xlsx)} file(s)")
            for xf in xlsx:
                print(f"    {xf.name}  ({_age_days(xf)}d old)")

    print("\n  Protected files:")
    for fname in NEVER_DELETE:
        fpath = _HERE / fname
        if fpath.exists():
            print(f"  ✅  {fname}  ({_size_mb(fpath):.2f}MB)")
        else:
            print(f"  ⚠️   {fname}  (not created yet)")

    print(f"\n  {'─' * 40}\n  Total project data : {total:>7.1f} MB\n" + "=" * 55)


def clean_old_csvs(dry_run=True):
    if not DATA_DIR.exists():
        return 0, 0.0, 0
    cutoff = datetime.now() - timedelta(days=KEEP_CSV_DAYS)
    deleted = freed = 0
    kept = 0
    for f in sorted(DATA_DIR.rglob("*")):
        if not f.is_file():
            continue
        if f.name in NEVER_DELETE:
            continue
        if f.suffix.lower() not in (".csv", ".dat", ".gz", ".zip"):
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        size = f.stat().st_size / 1_048_576
        if mtime < cutoff:
            if dry_run:
                print(f"    [WOULD DELETE] {f.name}  {size:.2f}MB  ({_age_days(f)}d old)")
            else:
                f.unlink()
                print(f"    [DELETED] {f.name}  {size:.2f}MB")
            deleted += 1
            freed += size
        else:
            kept += 1
    if not dry_run:
        for folder in sorted(DATA_DIR.rglob("*"), reverse=True):
            if folder.is_dir():
                with contextlib.suppress(OSError):
                    folder.rmdir()
    return deleted, freed, kept


def clean_old_logs(dry_run=True):
    if not LOG_DIR.exists():
        return 0, 0.0
    cutoff = datetime.now() - timedelta(days=KEEP_LOG_DAYS)
    deleted = freed = 0
    for f in LOG_DIR.rglob("*.log"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        size = f.stat().st_size / 1_048_576
        if mtime < cutoff:
            if dry_run:
                print(f"    [WOULD DELETE] {f.name}  {size:.2f}MB")
            else:
                f.unlink()
                print(f"    [DELETED] {f.name}  {size:.2f}MB")
            deleted += 1
            freed += size
    for f in LOG_DIR.glob("*.log"):
        if not f.exists():
            continue
        size = f.stat().st_size / 1_048_576
        if size > 5:
            if dry_run:
                print(f"    [WOULD TRIM]  {f.name}  {size:.1f}MB → keep last 1000 lines")
            else:
                lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
                f.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")
                saved = size - f.stat().st_size / 1_048_576
                freed += saved
                print(f"    [TRIMMED] {f.name}  saved {saved:.1f}MB")
    return deleted, freed


def clean_old_excel(dry_run=True):
    if not OUTPUT_DIR.exists():
        return 0, 0.0
    files = sorted(OUTPUT_DIR.glob("NSE_Scanner_*.xlsx"), key=lambda f: f.stat().st_mtime, reverse=True)
    to_del = files[KEEP_EXCEL:]
    deleted = freed = 0
    for f in to_del:
        size = f.stat().st_size / 1_048_576
        if dry_run:
            print(f"    [WOULD DELETE] {f.name}  {size:.2f}MB")
        else:
            f.unlink()
            print(f"    [DELETED] {f.name}  {size:.2f}MB")
        deleted += 1
        freed += size
    return deleted, freed


def clean_old_news(dry_run=True):
    if not OUTPUT_DIR.exists():
        return 0, 0.0
    cutoff = datetime.now() - timedelta(days=KEEP_NEWS_DAYS)
    deleted = freed = 0
    for f in OUTPUT_DIR.glob("news_*.json"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        size = f.stat().st_size / 1_048_576
        if mtime < cutoff:
            if dry_run:
                print(f"    [WOULD DELETE] {f.name}  {size:.2f}MB")
            else:
                f.unlink()
                print(f"    [DELETED] {f.name}  {size:.2f}MB")
            deleted += 1
            freed += size
    return deleted, freed


def run_cleanup(dry_run=True):
    mode = "DRY RUN" if dry_run else "LIVE CLEANUP"
    print(f"\n{'=' * 55}\n  NSE SPACE MANAGER — {mode}\n{'=' * 55}")
    _size_mb(DATA_DIR) + _size_mb(OUTPUT_DIR) + _size_mb(LOG_DIR)
    total_del = 0
    total_free = 0.0

    print(f"\n[1] Raw CSVs (keep {KEEP_CSV_DAYS} days)")
    d, f, kept = clean_old_csvs(dry_run)
    print(f"    → {d} files | {f:.1f}MB | {kept} kept")
    total_del += d
    total_free += f

    print(f"\n[2] Logs (keep {KEEP_LOG_DAYS} days)")
    d, f = clean_old_logs(dry_run)
    print(f"    → {d} deleted | {f:.1f}MB freed")
    total_del += d
    total_free += f

    print(f"\n[3] Excel (keep latest {KEEP_EXCEL})")
    d, f = clean_old_excel(dry_run)
    print(f"    → {d} deleted | {f:.1f}MB freed")
    total_del += d
    total_free += f

    print(f"\n[4] News JSON (keep {KEEP_NEWS_DAYS} days)")
    d, f = clean_old_news(dry_run)
    print(f"    → {d} deleted | {f:.1f}MB freed")
    total_del += d
    total_free += f

    print(f"\n{'─' * 55}\n  Total: {total_del} files | {total_free:.1f}MB freed")
    if dry_run and total_del > 0:
        print("  Run with --clean to actually free space")
    print("=" * 55 + "\n")
    return {"files_deleted": total_del, "mb_freed": round(total_free, 2), "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(description="NSE Scanner Space Manager")
    parser.add_argument("--clean", action="store_true", help="Actually delete")
    parser.add_argument("--status", action="store_true", help="Disk usage only")
    args = parser.parse_args()
    show_status()
    if args.status:
        return
    if args.clean:
        run_cleanup(dry_run=False)
    else:
        run_cleanup(dry_run=True)


if __name__ == "__main__":
    main()
