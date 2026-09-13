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


#!/usr/bin/env python3
"""
cleanup_nse_data.py — Safely delete old NSE data
=================================================
Deletes old data files while keeping recent data for analysis.

Usage:
    python cleanup_nse_data.py --help
    python cleanup_nse_data.py --delete-year 2025
    python cleanup_nse_data.py --delete-months 01,02,03
    python cleanup_nse_data.py --keep-months 3 --age-days 90
"""

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def safe_delete_directory(path, dry_run=True):
    """Safely delete a directory."""
    path_obj = Path(path)

    if not path_obj.exists():
        return False, f"Path doesn't exist: {path}"

    if not path_obj.is_dir():
        return False, f"Not a directory: {path}"

    size_mb = sum(f.stat().st_size for f in path_obj.rglob("*") if f.is_file()) / (1024 * 1024)
    file_count = sum(1 for _ in path_obj.rglob("*") if _.is_file())

    if dry_run:
        return True, f"[DRY RUN] Would delete {path} ({size_mb:.2f} MB, {file_count} files)"
    try:
        shutil.rmtree(path)
        return True, f"✅ Deleted {path} ({size_mb:.2f} MB, {file_count} files)"
    except Exception as e:
        return False, f"❌ Error deleting {path}: {e!s}"


def delete_year(year, dry_run=True):
    """Delete all data for a specific year."""
    year_path = Path("nse_data") / str(year)

    if not year_path.exists():
        print(f"❌ Year {year} directory not found")
        return False

    success, msg = safe_delete_directory(year_path, dry_run=dry_run)
    print(msg)
    return success


def delete_months(year, months, dry_run=True):
    """Delete specific months from a year."""
    year_path = Path("nse_data") / str(year)

    if not year_path.exists():
        print(f"❌ Year {year} directory not found")
        return False

    deleted_count = 0
    total_size = 0
    total_files = 0

    for month in months:
        month_path = year_path / month

        if not month_path.exists():
            print(f"⚠️  Month {year}/{month} not found")
            continue

        # Count files before deletion
        file_count = sum(1 for _ in month_path.rglob("*") if _.is_file())
        size_mb = sum(f.stat().st_size for f in month_path.rglob("*") if f.is_file()) / (1024 * 1024)

        if dry_run:
            print(f"[DRY RUN] Would delete {year}/{month} ({size_mb:.2f} MB, {file_count} files)")
        else:
            try:
                shutil.rmtree(month_path)
                print(f"✅ Deleted {year}/{month} ({size_mb:.2f} MB, {file_count} files)")
                deleted_count += 1
                total_size += size_mb
                total_files += file_count
            except Exception as e:
                print(f"❌ Error deleting {year}/{month}: {e!s}")

    if not dry_run and deleted_count > 0:
        print(f"\n✅ Total deleted: {deleted_count} months, {total_size:.2f} MB freed ({total_files} files)")

    return True


def keep_recent_months(keep_months=3, dry_run=True):
    """Keep only recent N months, delete older data."""
    nse_data_path = Path("nse_data")

    if not nse_data_path.exists():
        print("❌ nse_data directory not found")
        return False

    today = date.today()
    cutoff_date = today - timedelta(days=30 * keep_months)

    print(f"\n📅 Keeping data from last {keep_months} months (after {cutoff_date})")
    print(f"    Deleting data before: {cutoff_date}")
    print("-" * 60)

    total_deleted_size = 0
    total_deleted_files = 0

    for year_dir in sorted(nse_data_path.iterdir()):
        if not year_dir.is_dir():
            continue

        year = year_dir.name

        for month_dir in sorted(year_dir.iterdir()):
            if month_dir.name == "_monthly" or not month_dir.is_dir():
                continue

            # Create date from year/month
            try:
                month_date = datetime(int(year), int(month_dir.name), 1).date()
            except:
                continue

            if month_date < cutoff_date:
                file_count = sum(1 for _ in month_dir.rglob("*") if _.is_file())
                size_mb = sum(f.stat().st_size for f in month_dir.rglob("*") if f.is_file()) / (1024 * 1024)

                if dry_run:
                    print(
                        f"[DRY RUN] Would delete {year}/{month_dir.name:>2} ({size_mb:6.2f} MB, {file_count:4} files)"
                    )
                else:
                    try:
                        shutil.rmtree(month_dir)
                        print(f"✅ Deleted {year}/{month_dir.name:>2} ({size_mb:6.2f} MB, {file_count:4} files)")
                        total_deleted_size += size_mb
                        total_deleted_files += file_count
                    except Exception as e:
                        print(f"❌ Error: {year}/{month_dir.name}: {e!s}")

    if not dry_run:
        print(f"\n✅ Total freed: {total_deleted_size:.2f} MB ({total_deleted_files} files)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Safely delete old NSE data files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # See what would be deleted (dry run)
  python cleanup_nse_data.py --delete-year 2025

  # Actually delete a year
  python cleanup_nse_data.py --delete-year 2025 --confirm

  # Keep only 3 months of recent data
  python cleanup_nse_data.py --keep-months 3 --confirm

  # Delete specific months
  python cleanup_nse_data.py --delete-months 01,02,03 --year 2026 --confirm
        """,
    )

    parser.add_argument("--delete-year", type=int, help="Delete all data for a specific year")
    parser.add_argument("--delete-months", type=str, help="Delete specific months (comma-separated, e.g., 01,02,03)")
    parser.add_argument("--year", type=int, default=2026, help="Year for --delete-months option")
    parser.add_argument("--keep-months", type=int, help="Keep only recent N months, delete older data")
    parser.add_argument(
        "--confirm", action="store_true", help="Actually delete files (without this, only shows what would be deleted)"
    )
    parser.add_argument("--help-storage", action="store_true", help="Show storage recommendations")

    args = parser.parse_args()

    if args.help_storage:
        print("""
📌 WHEN TO DELETE NSE DATA:

✅ ALWAYS SAFE TO DELETE:
   • Previous year data (2025 if you're in 2026)
   • Data older than 6 months (unless you need historical analysis)

⚠️  OPTIONAL TO DELETE (with caution):
   • Data older than 3 months (minimum to keep for trend analysis)

❌ NEVER DELETE:
   • Current month's data (needed for active scanning)
   • Last 3 months of trading data (needed for pattern analysis)
   • Data you haven't backed up

💾 STORAGE ESTIMATES:
   • 3 months:  50-100 MB
   • 6 months: 100-200 MB
   • 1 year:   200-400 MB
   • 2 years:  400-800 MB

🔧 RECOMMENDED STRATEGY:
   1. Keep current year fully
   2. Keep 3-6 months of previous year
   3. Delete older years entirely
        """)
        return

    dry_run = not args.confirm

    if dry_run and not args.help_storage:
        print("\n⚠️  DRY RUN MODE - No files will be deleted")
        print("    Add --confirm flag to actually delete files")
        print("-" * 60)

    if args.delete_year:
        delete_year(args.delete_year, dry_run=dry_run)

    elif args.delete_months:
        months = [m.zfill(2) for m in args.delete_months.split(",")]
        delete_months(args.year, months, dry_run=dry_run)

    elif args.keep_months:
        keep_recent_months(args.keep_months, dry_run=dry_run)

    else:
        parser.print_help()

    if dry_run:
        print("\n💡 TIP: Run again with --confirm flag to actually delete")


if __name__ == "__main__":
    main()
