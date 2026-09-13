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
nse_historical_downloader.py — NSE Data Downloader
=====================================================
Downloads NSE daily files using TWO methods:

METHOD 1 — Direct Download (Automatic, 3 files):
    Works without any login or session:
    - sec_bhavdata_full  (OHLCV + delivery for all EQ stocks)
    - REG_IND            (regulatory blacklist)
    - ind_close_all      (all 147 index values)

METHOD 2 — Bundle ZIP (Manual drop, gives ALL files):
    Download manually from nseindia.com → place in drop_zone/
    Script auto-detects, extracts, and organises all files.
    Bundle contains: CMVOLT, PE, 52W H/L, MTO, PR bundle etc.

Usage:
    # Single date
    python nse_historical_downloader.py --date 05-03-2026

    # Date range
    python nse_historical_downloader.py --from 01-12-2025 --to 05-03-2026

    # Last N trading days
    python nse_historical_downloader.py --last 90

    # Process bundle ZIPs already in drop_zone/ folder
    python nse_historical_downloader.py --process-bundles

All dates: DD-MM-YYYY format.
Files saved to: nse_data/YYYY/MM/DD/
"""

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

import requests

# ── CONFIG ────────────────────────────────────────────────────
SAVE_ROOT = "nse_data"
DROP_ZONE = "drop_zone"  # Place bundle ZIPs here manually
LOG_DIR = "logs"
DELAY_SECS = 1.2  # Polite delay between requests
BOOTSTRAP_MAX_CANDIDATES = 520  # Weekdays examined to find valid EOD sessions

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

# ── NSE HOLIDAYS 2025-2026 ────────────────────────────────────
NSE_HOLIDAYS = {
    date(2025, 1, 26),
    date(2025, 2, 26),
    date(2025, 3, 14),
    date(2025, 3, 31),
    date(2025, 4, 14),
    date(2025, 4, 18),
    date(2025, 5, 1),
    date(2025, 8, 15),
    date(2025, 8, 27),
    date(2025, 10, 2),
    date(2025, 10, 21),
    date(2025, 10, 22),
    date(2025, 11, 5),
    date(2025, 12, 25),
    date(2026, 1, 26),
    date(2026, 3, 20),
    date(2026, 4, 3),
    date(2026, 8, 15),
    date(2026, 10, 2),
    date(2026, 11, 14),
    date(2026, 12, 25),
}

# ── WORKING DIRECT DOWNLOAD URLs ─────────────────────────────
# Confirmed working — tested 10-Mar-2026
DIRECT_URLS = {
    # ── CORE (always available) ──
    "sec_bhavdata_full": "https://archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv",
    "REG_IND": "https://archives.nseindia.com/content/cm/REG_IND{DDMMYY}.csv",
    "ind_close_all": "https://archives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv",
    # ── ADDITIONAL (volatility, 52W, PE) ──
    "CMVOLT": "https://archives.nseindia.com/archives/nsccl/volt/CMVOLT_{DDMMYYYY}.CSV",
    "CM_52_wk_High_low": "https://nsearchives.nseindia.com/content/CM_52_wk_High_low_{DDMMYYYY}.csv",
    "PE": "https://archives.nseindia.com/content/indices/PE_{DDMMYY}.csv",
}

# ── FILES EXPECTED FROM BUNDLE ZIP ───────────────────────────
# These come from Reports-Archives-Multiple-{date}.zip
# Download manually from nseindia.com and drop in drop_zone/
BUNDLE_FILES = [
    ("sec_bhavdata_full_{DDMMYYYY}.csv", "price + delivery data"),
    ("CMVOLT_{DDMMYYYY}.CSV", "volatility per stock"),
    ("CM_52_wk_High_low_{DDMMYYYY}.csv", "52-week high/low"),
    ("PE_{DDMMYY}.csv", "P/E ratios"),
    ("REG_IND{DDMMYY}.csv", "regulatory blacklist"),
    ("REG1_IND{DDMMYYYY}.csv", "extended regulatory flags"),
    ("MTO_{DDMMYYYY}.DAT", "delivery position"),
    ("shortselling_{DDMMYYYY}.csv", "short selling data"),
    ("PR{DDMMYY}.zip", "price report bundle"),
    ("NSE_CM_security_{DDMMYYYY}.csv.gz", "security master"),
]


# ─────────────────────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────────────────────


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NSE_HOLIDAYS


def get_trading_days(start: date, end: date) -> list:
    days, current = [], start
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def date_vars(d: date) -> dict:
    return {
        "DDMMYYYY": d.strftime("%d%m%Y"),
        "DDMMYY": d.strftime("%d%m%y"),
        "YYYYMMDD": d.strftime("%Y%m%d"),
        "MMMYYYY": d.strftime("%b%Y").upper(),
        "YYYY": d.strftime("%Y"),
        "MM": d.strftime("%m"),
        "DD": d.strftime("%d"),
        "display": d.strftime("%d-%b-%Y"),
    }


def apply_fmt(template: str, fmt: dict) -> str:
    """Replace {DDMMYYYY} style placeholders in a string."""
    result = template
    for k, v in fmt.items():
        result = result.replace("{" + k + "}", v)
    return result


def day_folder(d: date) -> str:
    """Returns: nse_data/2026/03/05"""
    fmt = date_vars(d)
    return os.path.join(SAVE_ROOT, fmt["YYYY"], fmt["MM"], fmt["DD"])


def ensure_dirs():
    for d in [SAVE_ROOT, DROP_ZONE, LOG_DIR]:
        os.makedirs(d, exist_ok=True)


# ─────────────────────────────────────────────────────────────
# LOG
# ─────────────────────────────────────────────────────────────


def log(msg: str):
    print(msg)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "downloader.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


# ─────────────────────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────────────────────


def download(url: str, save_path: str, retries: int = 2) -> bool:
    """Download one file. Returns True on success."""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    if os.path.exists(save_path) and os.path.getsize(save_path) > 500:
        fname = os.path.basename(save_path)
        print(f"   >> Already exists: {fname}")
        return True

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.content) > 100:
                with open(save_path, "wb") as f:
                    f.write(r.content)
                size_kb = os.path.getsize(save_path) / 1024
                fname = os.path.basename(save_path)
                print(f"   OK  {fname}  ({size_kb:.1f} KB)")
                log(f"Downloaded: {fname} ({size_kb:.1f} KB)")
                return True
            if r.status_code == 404:
                fname = os.path.basename(save_path)
                print(f"   404 {fname}  (not on server)")
                return False
            print(f"   ERR HTTP {r.status_code}: {os.path.basename(save_path)}")
            if attempt < retries:
                time.sleep(3)
        except Exception as e:
            print(f"   ERR {e}")
            if attempt < retries:
                time.sleep(5)
    return False


def extract_zip(zip_path: str, dest: str):
    """Extract ZIP file to dest folder."""
    try:
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(dest)
        print(f"   Extracted: {os.path.basename(zip_path)} -> {dest}")
    except Exception as e:
        print(f"   ZIP extract error: {e}")


def extract_gz(gz_path: str):
    """Extract .gz file in place."""
    out = gz_path[:-3]
    if os.path.exists(out):
        return
    try:
        with gzip.open(gz_path, "rb") as f_in, open(out, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        print(f"   Extracted GZ: {os.path.basename(out)}")
    except Exception as e:
        print(f"   GZ extract error: {e}")


# ─────────────────────────────────────────────────────────────
# METHOD 1 — DIRECT DOWNLOADS
# ─────────────────────────────────────────────────────────────


def download_direct(d: date) -> int:
    """
    Download the 3 files available via direct URL.
    Returns count of successful downloads.
    """
    fmt = date_vars(d)
    folder = day_folder(d)
    success = 0

    for url_template in DIRECT_URLS.values():
        url = apply_fmt(url_template, fmt)
        # Build filename from URL
        fname = url.split("/")[-1]
        savepath = os.path.join(folder, fname)
        if download(url, savepath):
            success += 1
        time.sleep(DELAY_SECS)

    return success


def _bhavdata_path(d: date) -> str:
    """Return the local path for the required historical EOD price file."""
    fmt = date_vars(d)
    return os.path.join(day_folder(d), f"sec_bhavdata_full_{fmt['DDMMYYYY']}.csv")


def has_valid_bhavdata(d: date) -> bool:
    """A historical session counts only when its Bhavdata has EQ price rows."""
    path = _bhavdata_path(d)
    if not os.path.exists(path) or os.path.getsize(path) <= 500:
        return False
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = {str(field).strip().upper() for field in (reader.fieldnames or [])}
            if "SYMBOL" not in fields or "SERIES" not in fields:
                return False
            for row in reader:
                # NSE CSV headers currently include leading spaces after commas
                # (for example, " SERIES").  Normalize each row before looking
                # up the fields so a valid historical file is not rejected.
                normalized_row = {str(key).strip().upper(): value for key, value in row.items() if key is not None}
                if (
                    str(normalized_row.get("SERIES", "")).strip().upper() == "EQ"
                    and str(normalized_row.get("SYMBOL", "")).strip()
                ):
                    return True
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    return False


def download_historical_bhavdata(d: date) -> bool:
    """Download and validate only the required historical EOD price file.

    Optional reports such as PE and volatility are deliberately excluded from
    bootstrap success criteria: they do not determine whether a price session
    is usable for long-horizon scanner calculations.
    """
    # A repeated bootstrap should validate already-downloaded sessions locally,
    # without making another NSE request.
    if has_valid_bhavdata(d):
        return True

    fmt = date_vars(d)
    url = apply_fmt(DIRECT_URLS["sec_bhavdata_full"], fmt)
    if not download(url, _bhavdata_path(d)):
        return False
    return has_valid_bhavdata(d)


def bootstrap_history(target_days: int, max_candidates: int = BOOTSTRAP_MAX_CANDIDATES):
    """Download until ``target_days`` valid Bhavdata sessions are available.

    NSE archive availability is the source of truth.  Weekdays with a holiday,
    archive 404, or malformed file are recorded and skipped rather than being
    counted as trading sessions.
    """
    if target_days <= 0:
        msg = "Bootstrap target must be positive"
        raise ValueError(msg)
    if max_candidates < target_days:
        msg = "max_candidates must be at least the requested target"
        raise ValueError(msg)

    latest_completed = date.today() - timedelta(days=1)
    cursor = latest_completed
    valid_dates, skipped_dates = [], []
    candidates = 0

    print(f"\n{'#' * 58}")
    print(f"  NSE HISTORY BOOTSTRAP — {target_days} VALID PRICE DAYS")
    print(f"  Checking up to {max_candidates} weekday candidates")
    print("  Historical mode downloads Bhavdata only")
    print(f"{'#' * 58}")

    while len(valid_dates) < target_days and candidates < max_candidates:
        if cursor.weekday() < 5:
            candidates += 1
            was_already_valid = has_valid_bhavdata(cursor)
            ok = download_historical_bhavdata(cursor)
            if ok:
                valid_dates.append(cursor.isoformat())
            else:
                skipped_dates.append(cursor.isoformat())

            if candidates % 10 == 0 or len(valid_dates) == target_days:
                print(
                    f"  Progress: valid={len(valid_dates)}/{target_days} | "
                    f"checked={candidates} | skipped={len(skipped_dates)}"
                )
            # Be polite only after an actual NSE request; local validation is
            # intentionally fast when resuming a bootstrap.
            if not was_already_valid:
                time.sleep(DELAY_SECS)
        cursor -= timedelta(days=1)

    manifest = {
        "target_valid_days": target_days,
        "valid_price_days": len(valid_dates),
        "candidate_weekdays_checked": candidates,
        "valid_dates": sorted(valid_dates),
        "skipped_dates": sorted(skipped_dates),
        "oldest_valid_date": min(valid_dates) if valid_dates else None,
        "newest_valid_date": max(valid_dates) if valid_dates else None,
    }
    manifest_path = os.path.join(SAVE_ROOT, "bootstrap_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    print(f"\n  Valid price days : {len(valid_dates)}")
    print(f"  Skipped dates    : {len(skipped_dates)}")
    print(f"  Manifest         : {manifest_path}")
    if len(valid_dates) < target_days:
        print(f"  ERROR: Only {len(valid_dates)} valid days found within {max_candidates} weekday candidates")
        return False
    print("  Bootstrap complete: required price history is available")
    return True


# ─────────────────────────────────────────────────────────────
# METHOD 2 — BUNDLE ZIP PROCESSING
# ─────────────────────────────────────────────────────────────


def extract_date_from_bundle(filename: str) -> date | None:
    """
    Extract date from bundle ZIP filename.
    Examples:
        Reports-Archives-Multiple-05032026.zip  -> date(2026,3,5)
        Reports-Archives-Multiple-06032026.zip  -> date(2026,3,6)
    """
    match = re.search(r"(\d{8})\.zip$", filename)
    if match:
        date_str = match.group(1)  # 05032026
        try:
            return datetime.strptime(date_str, "%d%m%Y").date()
        except ValueError:
            pass

    match = re.search(r"(\d{6})\.zip$", filename)
    if match:
        date_str = match.group(1)  # 050326
        try:
            return datetime.strptime(date_str, "%d%m%y").date()
        except ValueError:
            pass

    return None


def process_bundle(zip_path: str) -> bool:
    """
    Process a manually downloaded Reports-Archives-Multiple ZIP.
    Extracts all files and organises them into nse_data/YYYY/MM/DD/

    Args:
        zip_path: Path to the bundle ZIP file

    Returns:
        True if processed successfully
    """
    fname = os.path.basename(zip_path)
    print(f"\n   Processing bundle: {fname}")

    # ── Extract date from filename ──
    trade_date = extract_date_from_bundle(fname)
    if not trade_date:
        print(f"   WARN Cannot extract date from: {fname}")
        print("        Expected format: Reports-Archives-Multiple-DDMMYYYY.zip")
        return False

    fmt = date_vars(trade_date)
    folder = day_folder(trade_date)
    os.makedirs(folder, exist_ok=True)

    print(f"   Date: {fmt['display']} -> {folder}")

    # ── Extract bundle ZIP to temp folder ──
    temp_dir = os.path.join(DROP_ZONE, f"_temp_{fmt['DDMMYYYY']}")
    extract_zip(zip_path, temp_dir)

    # ── Walk all extracted files and copy to day folder ──
    copied = 0
    for root, _dirs, files in os.walk(temp_dir):
        for f in files:
            src = os.path.join(root, f)
            dest = os.path.join(folder, f)

            # Skip if already exists with same size
            if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(src):
                continue

            shutil.copy2(src, dest)
            print(f"   Copied: {f}")
            copied += 1

            # Auto-extract nested ZIPs (PR bundle, BhavCopy, Margintrdg)
            if f.endswith(".zip"):
                sub_dir = os.path.join(folder, f.replace(".zip", ""))
                extract_zip(dest, sub_dir)

            # Auto-extract GZ files
            if f.endswith(".gz"):
                extract_gz(dest)

    # ── Cleanup temp folder ──
    shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"   Done: {copied} files copied to {folder}")
    log(f"Bundle processed: {fname} -> {folder} ({copied} files)")
    return True


def process_all_bundles() -> int:
    """
    Scan drop_zone/ and process all bundle ZIPs found.
    Returns count of successfully processed bundles.
    """
    os.makedirs(DROP_ZONE, exist_ok=True)
    zips = [f for f in os.listdir(DROP_ZONE) if f.endswith(".zip") and not f.startswith("_")]

    if not zips:
        print(f"\n   No ZIP files found in {DROP_ZONE}/")
        print("   Download bundle from NSE website and drop it here.")
        print("   Expected filename: Reports-Archives-Multiple-DDMMYYYY.zip")
        return 0

    print(f"\n   Found {len(zips)} bundle(s) in {DROP_ZONE}/")
    success = 0

    for z in sorted(zips):
        zip_path = os.path.join(DROP_ZONE, z)
        ok = process_bundle(zip_path)
        if ok:
            success += 1
            # Move processed ZIP to done folder
            done_dir = os.path.join(DROP_ZONE, "processed")
            os.makedirs(done_dir, exist_ok=True)
            shutil.move(zip_path, os.path.join(done_dir, z))
            print(f"   Moved to: {done_dir}/{z}")

    return success


# ─────────────────────────────────────────────────────────────
# MAIN DATE RUNNER
# ─────────────────────────────────────────────────────────────


def run_for_date(d: date, include_monthly: bool = False):
    """Full download run for one trading day."""
    fmt = date_vars(d)

    print(f"\n{'=' * 58}")
    print(f"  Date: {fmt['display']}  ({d.strftime('%A')})")
    print(f"{'=' * 58}")

    # ── Direct downloads ──
    print("\n  [Direct Downloads]")
    direct_ok = download_direct(d)
    print(f"  -> {direct_ok}/{len(DIRECT_URLS)} direct files downloaded")

    # ── Monthly files ──
    if include_monthly:
        m_folder = os.path.join(SAVE_ROOT, fmt["YYYY"], fmt["MM"], "_monthly")
        os.makedirs(m_folder, exist_ok=True)
        print("\n  [Monthly Files]")
        monthly_urls = {
            "NSE_CM_security": f"https://archives.nseindia.com/products/content/NSE_CM_security_{fmt['DDMMYYYY']}.csv.gz",
            "C_CATG": f"https://archives.nseindia.com/content/cm/C_CATG_{fmt['MMMYYYY']}.T01",
        }
        for url in monthly_urls.values():
            fname = url.split("/")[-1]
            ok = download(url, os.path.join(m_folder, fname))
            if ok and fname.endswith(".gz"):
                extract_gz(os.path.join(m_folder, fname))
            time.sleep(DELAY_SECS)

    # ── Bundle reminder ──
    folder = day_folder(d)
    has_volt = os.path.exists(os.path.join(folder, f"CMVOLT_{fmt['DDMMYYYY']}.CSV"))

    if not has_volt:
        print("\n  [Bundle Files - Manual Step]")
        print("  For CMVOLT, PE, 52W H/L, PR bundle - download from NSE:")
        print("  1. Go to: https://www.nseindia.com/all-reports-detail-capital-market")
        print(f"  2. Select date: {fmt['display']}")
        print("  3. Click 'Download Multiple Reports'")
        print(f"  4. Save ZIP to: {DROP_ZONE}/")
        print("  5. Run: python nse_historical_downloader.py --process-bundles")


def run_range(start: date, end: date):
    """Download for a range of trading days."""
    days = get_trading_days(start, end)

    print(f"\n{'#' * 58}")
    print("  NSE Downloader — Date Range")
    print(f"  From    : {start.strftime('%d-%b-%Y')}")
    print(f"  To      : {end.strftime('%d-%b-%Y')}")
    print(f"  Trading days: {len(days)}")
    print(f"  Files/day   : {len(DIRECT_URLS)} direct files")
    print(f"{'#' * 58}")

    if not days:
        print("No trading days in range.")
        return

    ans = input("\nProceed? (y/n): ").strip().lower()
    if ans != "y":
        print("Cancelled.")
        return

    months_done = set()

    for i, d in enumerate(days):
        month_key = (d.year, d.month)
        do_monthly = month_key not in months_done
        if do_monthly:
            months_done.add(month_key)

        run_for_date(d, include_monthly=do_monthly)

        pct = (i + 1) / len(days) * 100
        print(f"\n  Progress: {i + 1}/{len(days)} days ({pct:.0f}%)")

    print(f"\n{'#' * 58}")
    print("  Download complete!")
    print(f"  Files in: {os.path.abspath(SAVE_ROOT)}")
    print(f"{'#' * 58}")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────


def parse_date_arg(s: str) -> date:
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    print(f"Invalid date: '{s}'. Use DD-MM-YYYY (e.g. 05-03-2026)")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="NSE Historical Data Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nse_historical_downloader.py --date 05-03-2026
  python nse_historical_downloader.py --from 01-01-2026 --to 05-03-2026
  python nse_historical_downloader.py --last 90
  python nse_historical_downloader.py --bootstrap 420
  python nse_historical_downloader.py --process-bundles
        """,
    )

    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--date", type=str, help="Single date DD-MM-YYYY or today/yesterday")
    grp.add_argument("--from", type=str, dest="date_from", metavar="DD-MM-YYYY")
    grp.add_argument("--last", type=int, metavar="N", help="Last N trading days")
    grp.add_argument(
        "--bootstrap",
        type=int,
        metavar="VALID_DAYS",
        help="Download until this many valid Bhavdata price sessions exist",
    )
    grp.add_argument("--process-bundles", action="store_true", help="Process all ZIPs in drop_zone/ folder")

    parser.add_argument("--to", type=str, dest="date_to", metavar="DD-MM-YYYY")
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=BOOTSTRAP_MAX_CANDIDATES,
        help="Maximum weekday dates examined by --bootstrap (default: 520)",
    )
    args = parser.parse_args()

    ensure_dirs()
    today = date.today()

    # ── Process bundles ──
    if args.process_bundles:
        print("\n  Processing bundle ZIPs from drop_zone/...")
        n = process_all_bundles()
        print(f"\n  {n} bundle(s) processed.")
        return

    # ── Valid-price bootstrap ──
    if args.bootstrap:
        ok = bootstrap_history(args.bootstrap, args.max_candidates)
        sys.exit(0 if ok else 1)

    # ── Single date ──
    if args.date:
        d = (
            today
            if args.date == "today"
            else today - timedelta(days=1)
            if args.date == "yesterday"
            else parse_date_arg(args.date)
        )
        run_for_date(d, include_monthly=(today.day == 1))

    # ── Date range ──
    elif args.date_from:
        start = parse_date_arg(args.date_from)
        end = parse_date_arg(args.date_to) if args.date_to else today
        run_range(start, end)

    # ── Last N days ──
    elif args.last:
        count, d = 0, today
        while count < args.last:
            d -= timedelta(days=1)
            if is_trading_day(d):
                count += 1
        run_range(d, today - timedelta(days=1))


if __name__ == "__main__":
    main()
