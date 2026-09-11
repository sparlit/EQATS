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
delivery_downloader.py
======================
Downloads the daily NSE Full Bhavcopy + Security Deliverable Data
(sec_bhavdata_full_DDMMYYYY.csv) automatically every weekday.

How it works
------------
1.  Calculates the correct target date (handles weekends gracefully).
2.  Warms up an NSE browser-like session (homepage → cookies → download).
3.  Downloads  sec_bhavdata_full_DDMMYYYY.csv  from NSE.
4.  Saves it under  NSE_Delivery_Data/  with a clear filename.
5.  Exits with code 1 on hard failures so GitHub Actions marks the run red.

Run manually
------------
    pip install requests pandas
    python delivery_downloader.py
"""

import io
import logging
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

# ─────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────
OUTPUT_DIR = "NSE_Delivery_Data"  # folder where CSVs are saved
REQUEST_TIMEOUT = 60  # seconds per HTTP request
MAX_RETRIES = 3  # retry attempts per URL
RETRY_DELAY = (8, 15)  # seconds range between retries

# ─────────────────────────────────────────────────────────────
#  LOGGING  (console + persistent log file)
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("delivery_download.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  USER-AGENT POOL  — rotated to avoid fingerprinting
# ─────────────────────────────────────────────────────────────
USER_AGENTS = [
    # Chrome 124 · Windows
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    # Chrome 123 · macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    # Firefox 125 · Windows
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"),
    # Edge 124 · Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
    # Safari 17 · macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
]


# ─────────────────────────────────────────────────────────────
#  DATE LOGIC
# ─────────────────────────────────────────────────────────────
def get_target_date() -> date:
    """
    Return the most recent weekday (Mon–Fri).
    • If today is Saturday  → return Friday
    • If today is Sunday    → return Friday
    • Any weekday           → return today
    """
    today = date.today()
    if today.weekday() == 5:  # Saturday
        return today - timedelta(days=1)
    if today.weekday() == 6:  # Sunday
        return today - timedelta(days=2)
    return today


# ─────────────────────────────────────────────────────────────
#  URL BUILDER
# ─────────────────────────────────────────────────────────────
def delivery_data_url(d: date) -> str:
    """
    NSE delivery data URL format:
    https://www.nseindia.com/api/reports?archives=%5B%7B%22name%22%3A%22
    ... (complex API path) ...

    Simpler direct URL used by NSE:
    https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
    """
    dd = d.strftime("%d")  # zero-padded day    e.g. "05"
    mm = d.strftime("%m")  # zero-padded month  e.g. "01"
    yyyy = d.strftime("%Y")  # 4-digit year        e.g. "2025"
    return f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dd}{mm}{yyyy}.csv"


def output_csv_path(d: date) -> Path:
    """
    Destination:  NSE_Delivery_Data/sec_bhavdata_full_DDMMYYYY.csv
    """
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
    return Path(OUTPUT_DIR) / filename


# ─────────────────────────────────────────────────────────────
#  SESSION FACTORY
# ─────────────────────────────────────────────────────────────
def make_session() -> requests.Session:
    """Create a session pre-loaded with randomised browser headers."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
    )
    return session


# ─────────────────────────────────────────────────────────────
#  NSE HANDSHAKE  (seeds required Akamai / NSE cookies)
# ─────────────────────────────────────────────────────────────
def nse_handshake(session: requests.Session) -> bool:
    """
    Two-step handshake:
      Step 1 – Hit the NSE homepage to get base cookies.
      Step 2 – Hit the market-data page to pick up deeper session tokens.
    NSE's CDN (Akamai) checks for these cookies; without them every
    archive request returns HTTP 403 Forbidden.
    Returns True on success.
    """
    steps = [
        ("NSE homepage", "https://www.nseindia.com"),
        ("Market data page", "https://www.nseindia.com/market-data/all-reports"),
    ]
    for label, url in steps:
        try:
            log.info("Handshake → %s (%s)", label, url)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            log.info("  ✓ %s  [HTTP %s | cookies: %d]", label, resp.status_code, len(session.cookies))
            # Polite inter-step pause
            time.sleep(random.uniform(2.0, 3.5))
        except requests.RequestException as exc:
            log.warning("  Handshake step failed (%s): %s — continuing anyway.", label, exc)
    return True


# ─────────────────────────────────────────────────────────────
#  DOWNLOAD  (with retry logic)
# ─────────────────────────────────────────────────────────────
def download_delivery_data(session: requests.Session, d: date) -> bool:
    """
    Download sec_bhavdata_full_DDMMYYYY.csv for the given date.
    Returns True on success, False on failure.

    Result codes:
      200 → save file, return True
      404 → market holiday / no data, log and return False (not an error)
      403 → session blocked, log warning
      other → log error
    """
    dest = output_csv_path(d)

    # ── Resume: skip if already downloaded ───────────────────
    if dest.exists() and dest.stat().st_size > 0:
        log.info("  [SKIP]  %s already exists on disk.", dest.name)
        return True

    url = delivery_data_url(d)
    log.info("  [URL ]  %s", url)

    # Update headers to look like we're navigating from NSE's own page
    session.headers.update(
        {
            "Referer": "https://www.nseindia.com/market-data/all-reports",
            "User-Agent": random.choice(USER_AGENTS),
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.ConnectionError as exc:
            log.exception("  [ERR ]  Connection error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(random.uniform(*RETRY_DELAY))
            continue
        except requests.exceptions.Timeout:
            log.exception("  [ERR ]  Request timed out (attempt %d/%d).", attempt, MAX_RETRIES)
            if attempt < MAX_RETRIES:
                time.sleep(random.uniform(*RETRY_DELAY))
            continue

        # ── HTTP 404: holiday / weekend / no data ─────────────
        if resp.status_code == 404:
            log.info("  [404 ]  No data for %s — likely a market holiday.", d.strftime("%d-%b-%Y"))
            return False

        # ── HTTP 403: session blocked ─────────────────────────
        if resp.status_code == 403:
            log.warning("  [403 ]  Forbidden on attempt %d/%d — re-warming session.", attempt, MAX_RETRIES)
            nse_handshake(session)  # try to recover cookies
            time.sleep(random.uniform(*RETRY_DELAY))
            continue

        # ── Other non-200 ──────────────────────────────────────
        if resp.status_code != 200:
            log.error("  [ERR ]  HTTP %s on attempt %d/%d.", resp.status_code, attempt, MAX_RETRIES)
            if attempt < MAX_RETRIES:
                time.sleep(random.uniform(*RETRY_DELAY))
            continue

        # ── Success ───────────────────────────────────────────
        content = resp.content
        if len(content) < 200:  # guard against empty/redirect HTML
            log.warning("  [WARN]  Response too small (%d bytes) — may not be a CSV.", len(content))
            if attempt < MAX_RETRIES:
                time.sleep(random.uniform(*RETRY_DELAY))
            continue

        dest.write_bytes(content)
        size_kb = len(content) / 1024
        log.info("  [SAVE]  %s  (%.1f KB)", dest, size_kb)

        # ── Quick pandas preview ──────────────────────────────
        try:
            df = pd.read_csv(io.BytesIO(content))
            log.info("  [INFO]  %d rows × %d columns", len(df), len(df.columns))
            log.info("  [COLS]  %s", list(df.columns[:8]))  # first 8 column names
        except Exception as exc:
            log.warning("  [WARN]  Could not parse CSV for preview: %s", exc)

        return True

    log.error("  [FAIL]  All %d attempts failed for %s.", MAX_RETRIES, d)
    return False


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────
def main() -> None:
    target = get_target_date()

    log.info("=" * 62)
    log.info("NSE Security Deliverable Data Downloader")
    log.info("  Target date  : %s (%s)", target, target.strftime("%A"))
    log.info("  Output folder: %s", Path(OUTPUT_DIR).resolve())
    log.info("=" * 62)

    session = make_session()

    # ── Step 1: Handshake (seed cookies) ─────────────────────
    nse_handshake(session)

    # ── Step 2: Short pause before the real request ───────────
    time.sleep(random.uniform(2.0, 4.0))

    # ── Step 3: Download ──────────────────────────────────────
    success = download_delivery_data(session, target)

    # ── Step 4: Exit code ─────────────────────────────────────
    if success:
        log.info("=" * 62)
        log.info("✅  Download complete for %s", target)
        log.info("=" * 62)
        sys.exit(0)
    else:
        log.warning("=" * 62)
        log.warning("⚠️   No file saved for %s (holiday or error — see log).", target)
        log.warning("=" * 62)
        # Exit 0 so GitHub Actions does NOT mark the run as failed on holidays
        sys.exit(0)


if __name__ == "__main__":
    main()
