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
nse_historical_bhav.py
======================
Downloads historical NSE Equity Full Bhav Copy (containing end-of-day Delivery Data)
CSV files for any user-specified date range with an organized Year/Month folder structure.

Usage
-----
1. Edit START_DATE / END_DATE constants below, then run:
       python nse_historical_bhav.py

2. Or pass dates on the command line:
       python nse_historical_bhav.py --start 2023-01-01 --end 2023-12-31
"""

# ─────────────────────────────────────────────────────────────
#  USER CONFIGURATION  ← edit these if not using CLI arguments
# ─────────────────────────────────────────────────────────────
START_DATE = "2020-01-01"  # YYYY-MM-DD
END_DATE = "2022-12-31"  # YYYY-MM-DD
OUTPUT_ROOT = "./HistoricalBhavCopy/NSE"  # base output folder


# ─────────────────────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────────────────────
import argparse
import io
import logging
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

# ─────────────────────────────────────────────────────────────
#  LOGGING  (console + file)
# ─────────────────────────────────────────────────────────────
LOG_FILE = "bhav_download.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  USER-AGENT POOL  (rotated per request to avoid fingerprinting)
# ─────────────────────────────────────────────────────────────
USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-IN,en;q=0.9,hi;q=0.8",
]


# ─────────────────────────────────────────────────────────────
#  SESSION FACTORY
# ─────────────────────────────────────────────────────────────
def make_session() -> requests.Session:
    """Create a requests.Session with rotating browser-like headers."""
    session = requests.Session()
    _refresh_headers(session)
    session.cookies.clear()
    return session


def _refresh_headers(session: requests.Session) -> None:
    """Rotate User-Agent and Accept-Language for the next request."""
    session.headers.update(
        {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": random.choice(ACCEPT_LANGUAGES),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
    )


# ─────────────────────────────────────────────────────────────
#  NSE SESSION WARM-UP
# ─────────────────────────────────────────────────────────────
def warm_up_nse(session: requests.Session) -> bool:
    """Visit NSE homepage to seed cookies required by CDN."""
    log.info("Warming up NSE session (acquiring cookies)…")
    try:
        r = session.get("https://www.nseindia.com", timeout=30)
        r.raise_for_status()
        time.sleep(random.uniform(1.5, 2.5))
        session.headers["Referer"] = "https://www.nseindia.com/"
        r2 = session.get("https://www.nseindia.com/market-data/all-reports", timeout=30)
        log.info("NSE warm-up done  (status %s | cookies: %d)", r2.status_code, len(session.cookies))
        return True
    except Exception as exc:
        log.warning("NSE warm-up failed (will still attempt downloads): %s", exc)
        return False


# ─────────────────────────────────────────────────────────────
#  URL + PATH BUILDERS
# ─────────────────────────────────────────────────────────────
def nse_csv_filename(d: date) -> str:
    """Generates the file name for delivery-inclusive bhav copies."""
    return f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def nse_url(d: date) -> str:
    """
    NSE historical delivery archive URL pattern:
    https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
    """
    return f"https://archives.nseindia.com/products/content/{nse_csv_filename(d)}"


def output_csv_path(d: date, root: str) -> Path:
    """
    Target path: <root>/<YYYY>/<MM_Month>/sec_bhavdata_full_DDMMYYYY.csv
    Example: ./HistoricalBhavCopy/NSE/2023/05_May/sec_bhavdata_full_15052023.csv
    """
    # Create month string like '01_Jan', '02_Feb', etc. to keep folders ordered chronologically
    month_str = f"{d.strftime('%m')}_{d.strftime('%b')}"

    # Chain directories together: Root -> Year -> Month
    target_dir = Path(root) / str(d.year) / month_str
    target_dir.mkdir(parents=True, exist_ok=True)

    return target_dir / nse_csv_filename(d)


# ─────────────────────────────────────────────────────────────
#  DOWNLOAD  (single day)
# ─────────────────────────────────────────────────────────────
class DownloadResult:
    DOWNLOADED = "DOWNLOADED"
    SKIPPED = "SKIPPED"
    HOLIDAY = "HOLIDAY"
    ERROR = "ERROR"


def download_day(session: requests.Session, d: date, output_root: str) -> str:
    dest_csv = output_csv_path(d, output_root)

    # Skip if already downloaded
    if dest_csv.exists():
        log.info("  [SKIP]      %s  (already downloaded)", dest_csv.name)
        return DownloadResult.SKIPPED

    url = nse_url(d)
    log.info("  [FETCH]     %s", url)

    _refresh_headers(session)
    session.headers["Referer"] = "https://www.nseindia.com/market-data/all-reports"

    try:
        resp = session.get(url, timeout=45, stream=True)
    except Exception as exc:
        log.exception("  [ERROR]     Connection error for %s: %s", d, exc)
        return DownloadResult.ERROR

    if resp.status_code == 404:
        log.info("  [HOLIDAY]   %s → 404 (market holiday or no data)", d.strftime("%d-%b-%Y"))
        return DownloadResult.HOLIDAY

    if resp.status_code == 403:
        log.warning("  [BLOCKED]   %s → 403 Forbidden. Re-warming session might be needed.", d)
        return DownloadResult.ERROR

    if resp.status_code != 200:
        log.error("  [ERROR]     %s → HTTP %s", d, resp.status_code)
        return DownloadResult.ERROR

    csv_content = resp.content

    # Sanity check: ensure payload isn't a blocked HTML landing page
    if b"html" in csv_content[:200].lower() or len(csv_content) < 1000:
        log.error("  [ERROR]     Received invalid non-CSV or empty payload for %s", d)
        return DownloadResult.ERROR

    # Write raw CSV data down
    dest_csv.write_bytes(csv_content)
    log.info("  [SAVED]     %s  (%d KB)", dest_csv.name, len(csv_content) // 1024)
    return DownloadResult.DOWNLOADED


# ─────────────────────────────────────────────────────────────
#  DATE RANGE ITERATOR
# ─────────────────────────────────────────────────────────────
def weekdays_between(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


# ─────────────────────────────────────────────────────────────
#  MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────
def run(start: date, end: date, output_root: str) -> None:
    all_days = list(weekdays_between(start, end))
    total = len(all_days)

    log.info("=" * 60)
    log.info("NSE Full Delivery Bhav Copy Downloader")
    log.info("  Date range : %s → %s", start, end)
    log.info("  Weekdays   : %d", total)
    log.info("  Output root: %s", Path(output_root).resolve())
    log.info("=" * 60)

    if total == 0:
        log.warning("No weekdays found in range.")
        return

    stats = dict.fromkeys(
        (DownloadResult.DOWNLOADED, DownloadResult.SKIPPED, DownloadResult.HOLIDAY, DownloadResult.ERROR), 0
    )

    session = make_session()
    warm_up_nse(session)

    REWARM_EVERY = 25

    for idx, day in enumerate(all_days, start=1):
        if idx > 1 and (idx - 1) % REWARM_EVERY == 0:
            log.info("── Re-warming NSE session (request %d / %d) ──", idx, total)
            warm_up_nse(session)

        log.info("[%4d / %4d]  %s", idx, total, day.strftime("%A, %d %b %Y"))

        result = download_day(session, day, output_root)
        stats[result] += 1

        if result == DownloadResult.DOWNLOADED:
            delay = random.uniform(1.5, 3.5)
        elif result == DownloadResult.ERROR:
            delay = random.uniform(5.0, 10.0)
        else:
            delay = random.uniform(0.3, 1.0)

        time.sleep(delay)

    log.info("\n" + "=" * 60)
    log.info("DOWNLOAD COMPLETE")
    log.info("  ✅  Downloaded : %d", stats[DownloadResult.DOWNLOADED])
    log.info("  ⏭️  Skipped    : %d", stats[DownloadResult.SKIPPED])
    log.info("  📅  Holidays   : %d", stats[DownloadResult.HOLIDAY])
    log.info("  ❌  Errors     : %d", stats[DownloadResult.ERROR])
    log.info("=" * 60)


def parse_args() -> tuple[date, date, str]:
    parser = argparse.ArgumentParser(description="Download historical NSE Full Bhav Copy CSV files.")
    parser.add_argument("--start", default=START_DATE, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=END_DATE, help="End date YYYY-MM-DD")
    parser.add_argument("--out", default=OUTPUT_ROOT, help="Output root folder")
    args = parser.parse_args()

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        parser.error(f"Invalid date format: {exc} (expected YYYY-MM-DD)")

    if start > end:
        parser.error("--start must be on or before --end")

    return start, end, args.out


if __name__ == "__main__":
    start_date, end_date, out_root = parse_args()
    run(start_date, end_date, out_root)
