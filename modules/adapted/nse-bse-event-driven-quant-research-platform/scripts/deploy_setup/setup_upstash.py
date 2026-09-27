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


"""Upstash Redis setup — Phase 2: Login + create Redis database + extract URL.

Reads credentials from accounts.json (created by create_accounts.py).
Uses saved cookies for session reuse.
"""


import json
import re
from contextlib import suppress
from pathlib import Path

from seleniumbase import SB

COOKIES_FILE = Path(__file__).parent / ".cookies_upstash.txt"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"


def _load_credentials() -> tuple[str, str]:
    """Load Upstash credentials from accounts.json."""
    if ACCOUNTS_FILE.exists():
        accounts = json.loads(ACCOUNTS_FILE.read_text())
        if "upstash" in accounts:
            return accounts["upstash"]["email"], accounts["upstash"]["password"]

    print("  No saved Upstash credentials found.")
    email = input("  Upstash email: ").strip()
    password = input("  Upstash password: ").strip()
    return email, password


def setup_upstash(db_name: str = "nse-bse-quant") -> tuple[str, str, str]:
    """Login to Upstash, create Redis database, extract URL.

    Returns:
        (email, password, redis_url)
    """
    email, password = _load_credentials()

    print(f"  [1/3] Logging in as {email}...")
    redis_url = _create_redis_db(email, password, db_name)

    if redis_url:
        print("  [✓] Redis URL obtained")
    else:
        print("  [!] Could not extract Redis URL")

    return email, password, redis_url


def _create_redis_db(email: str, password: str, db_name: str) -> str:
    """Login to Upstash, create/select Redis database, return URL."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://console.upstash.com/login")
        sb.sleep(8)

        # Login if needed
        current_url = sb.get_current_url()
        if "login" in current_url:
            with suppress(Exception):
                sb.type('input[type="email"], input[name="email"]', email, timeout=5)
                sb.sleep(0.3)
            with suppress(Exception):
                sb.type('input[type="password"], input[name="password"]', password, timeout=3)
                sb.sleep(0.3)
            with suppress(Exception):
                sb.click('button[type="submit"], button:contains("Sign in")', timeout=5)
            sb.sleep(8)

        sb.save_cookies(str(COOKIES_FILE))

        # Navigate to Redis
        sb.goto("https://console.upstash.com/redis")
        sb.sleep(5)

        # Check if database exists
        if sb.is_text_visible(db_name):
            sb.click(f'text="{db_name}"')
            sb.sleep(3)
        else:
            # Create new database
            with suppress(Exception):
                sb.click('button:contains("Create Database"), button:contains("New")', timeout=5)
            sb.sleep(2)

            with suppress(Exception):
                name_input = sb.find_element('input[name="name"], input[placeholder*="name"]', timeout=5)
                name_input.clear()
                sb.type('input[name="name"], input[placeholder*="name"]', db_name)

            with suppress(Exception):
                sb.select_option_by_text('select[name="region"], select', "ap-south-1 (Mumbai)")

            with suppress(Exception):
                sb.click('button:contains("Create"), button[type="submit"]', timeout=5)
            sb.sleep(5)

        return _extract_redis_url(sb)


def _extract_redis_url(sb: SB) -> str:
    """Extract Redis URL from Upstash dashboard."""
    selectors = [
        "code",
        "pre",
        "input[readonly]",
        "[data-clipboard-text]",
        '[class*="connection"]',
        '[class*="url"]',
    ]

    for sel in selectors:
        with suppress(Exception):
            elements = sb.find_elements(sel)
            for el in elements:
                txt = el.get_attribute("data-clipboard-text") or el.text or el.get_attribute("value") or ""
                if "rediss://" in txt or "redis://" in txt:
                    return txt.strip()

    source = sb.get_page_source()
    match = re.search(r'rediss?://[^\s"<>\'&]+', source)
    if match:
        return match.group(0)

    return ""


def verify_upstash_connection(url: str) -> bool:
    """Quick verify the Upstash Redis connection works."""
    try:
        import redis

        r = redis.from_url(url, socket_timeout=5)
        return r.ping()
    except Exception as e:
        print(f"  [!] Upstash connection failed: {e}")
        return False


if __name__ == "__main__":
    email, password, url = setup_upstash()
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  Redis URL: {url}")
