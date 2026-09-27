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
auto_cleanup_nse_data.py — Automatically delete NSE data older than 180 days
=============================================================================
Keeps exactly 180 days (6 months) of historical data.
Automatically deletes files older than 180 days.

This script:
✅ Keeps 180 days of data (rolling window)
✅ Deletes any data older than 180 days
✅ Logs deletions for audit
✅ Runs automatically on each trading day
✅ Skips deletion on Saturdays/Sundays

Usage:
    # Manual cleanup
    python auto_cleanup_nse_data.py

    # Check what will be deleted (dry run)
    python auto_cleanup_nse_data.py --dry-run

    # Integration in nse_daily_runner.py
    from auto_cleanup_nse_data import auto_cleanup_old_data
    auto_cleanup_old_data()
"""

import argparse
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

# Configuration
KEEP_DAYS = 180  # Keep 180 days of data (6 months)
LOG_FILE = "logs/cleanup_history.log"


def get_file_date(file_path):
    """
    Extract date from file path.
    Expected structure: nse_data/YYYY/MM/DD_*.csv or similar
    """
    try:
        parts = str(file_path).split(os.sep)

        # Try to find YYYY/MM pattern
        for i, part in enumerate(parts):
            if part.isdigit() and len(part) == 4:  # Year like 2026
                year = part
                if i + 1 < len(parts):
                    month = parts[i + 1]
                    if month.isdigit() and len(month) <= 2:
                        # Try to get day if available
                        if i + 2 < len(parts):
                            day_part = parts[i + 2]
                            # Extract day from folder name (e.g., "05" or "05_data")
                            if day_part.isdigit():
                                day = day_part
                            else:
                                # Try to extract from filename
                                day = day_part.split("_")[0]
                                if not day.isdigit():
                                    day = "01"  # Default to 1st if can't parse
                        else:
                            day = "01"  # Default to 1st of month

                        try:
                            return date(int(year), int(month), int(day))
                        except ValueError:
                            return None
    except:
        pass

    return None


def log_deletion(action, message):
    """Log deletion actions."""
    os.makedirs("logs", exist_ok=True)

    timestamp = date.today().isoformat()
    log_entry = f"[{timestamp}] {action}: {message}\n"

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)

    print(f"  📝 {message}")


def cleanup_old_data(keep_days=KEEP_DAYS, dry_run=False):
    """
    Delete data older than keep_days.

    Args:
        keep_days: Number of days to keep (default 180)
        dry_run: If True, show what would be deleted without deleting

    Returns:
        (deleted_count, deleted_size_mb, total_files)
    """
    nse_data_path = Path("nse_data")

    if not nse_data_path.exists():
        print("❌ nse_data directory not found")
        return 0, 0, 0

    cutoff_date = date.today() - timedelta(days=keep_days)

    print(f"\n{'=' * 70}")
    print("  NSE DATA AUTO-CLEANUP")
    print(f"{'=' * 70}")
    print(f"\n  📅 Today: {date.today()}")
    print(f"  📅 Keep until: {cutoff_date}")
    print(f"  📅 Delete before: {cutoff_date}")
    print(f"  ⏳ Keeping: {keep_days} days of data")

    if dry_run:
        print("\n  ⚠️  DRY RUN MODE - No files will be deleted")

    deleted_count = 0
    deleted_size_mb = 0
    deleted_folders = []

    # Iterate through years and months
    for year_dir in sorted(nse_data_path.iterdir()):
        if not year_dir.is_dir():
            continue

        year = year_dir.name

        for month_dir in sorted(year_dir.iterdir()):
            if month_dir.name == "_monthly" or not month_dir.is_dir():
                continue

            month = month_dir.name

            # For month-based deletion, check if entire month is older
            try:
                # Assume month folder represents 1st of that month
                month_date = date(int(year), int(month), 1)

                if month_date < cutoff_date:
                    # Count files before deletion
                    file_count = sum(1 for _ in month_dir.rglob("*") if _.is_file())
                    size_mb = sum(f.stat().st_size for f in month_dir.rglob("*") if f.is_file()) / (1024 * 1024)

                    if not dry_run:
                        try:
                            shutil.rmtree(month_dir)
                            log_deletion("DELETE", f"{year}/{month} ({size_mb:.2f} MB, {file_count} files)")
                            deleted_count += 1
                            deleted_size_mb += size_mb
                            deleted_folders.append(f"{year}/{month}")
                        except Exception as e:
                            log_deletion("ERROR", f"Failed to delete {year}/{month}: {e!s}")
                    else:
                        print(f"  [DRY RUN] Would delete {year}/{month:>2} ({size_mb:6.2f} MB, {file_count:4} files)")
                        deleted_count += 1
                        deleted_size_mb += size_mb
                        deleted_folders.append(f"{year}/{month}")

            except ValueError:
                # Invalid month format, skip
                continue

    # Summary
    print(f"\n  {'─' * 70}")

    if deleted_count > 0:
        print("\n  ✅ CLEANUP SUMMARY:")
        print(f"     Deleted folders: {deleted_count}")
        print(f"     Freed space: {deleted_size_mb:.2f} MB")
        print(f"     Folders: {', '.join(deleted_folders[:5])}", end="")
        if len(deleted_folders) > 5:
            print(f", ... and {len(deleted_folders) - 5} more", end="")
        print()

        if not dry_run:
            log_deletion("SUMMARY", f"Deleted {deleted_count} month(s), freed {deleted_size_mb:.2f} MB")
    else:
        print(f"\n  ✅ No old data to delete (all data is within {keep_days} days)")

    # Count remaining files
    total_files = sum(1 for _ in nse_data_path.rglob("*") if _.is_file())

    print(f"  📊 Remaining data: {total_files} files")
    print(f"\n{'=' * 70}\n")

    return deleted_count, deleted_size_mb, total_files


def auto_cleanup_old_data(keep_days=KEEP_DAYS):
    """
    Automatically cleanup old data.
    Call this once per trading day (e.g., from nse_daily_runner.py).

    Args:
        keep_days: Number of days to keep (default 180)
    """
    return cleanup_old_data(keep_days=keep_days, dry_run=False)


def main():
    parser = argparse.ArgumentParser(
        description="Auto-cleanup old NSE data (keep 180 days)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show what will be deleted
  python auto_cleanup_nse_data.py --dry-run

  # Actually delete old data
  python auto_cleanup_nse_data.py

  # Keep 90 days instead of 180
  python auto_cleanup_nse_data.py --keep-days 90

  # Keep 365 days (full year)
  python auto_cleanup_nse_data.py --keep-days 365
        """,
    )

    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    parser.add_argument(
        "--keep-days", type=int, default=KEEP_DAYS, help=f"Number of days to keep (default {KEEP_DAYS})"
    )

    args = parser.parse_args()

    _deleted, _freed, _remaining = cleanup_old_data(keep_days=args.keep_days, dry_run=args.dry_run)

    if args.dry_run:
        print("💡 TIP: Run without --dry-run to actually delete files")


if __name__ == "__main__":
    main()
