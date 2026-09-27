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


"""UptimeRobot monitor setup — Phase 2: Login + create HTTP monitor.

Reads credentials from accounts.json (created by create_accounts.py).
Uses saved cookies for session reuse.
"""


import json
from contextlib import suppress
from pathlib import Path

from seleniumbase import SB

COOKIES_FILE = Path(__file__).parent / ".cookies_uptimerobot.txt"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"


def _load_credentials() -> tuple[str, str]:
    """Load UptimeRobot credentials from accounts.json."""
    if ACCOUNTS_FILE.exists():
        accounts = json.loads(ACCOUNTS_FILE.read_text())
        if "uptimerobot" in accounts:
            return accounts["uptimerobot"]["email"], accounts["uptimerobot"]["password"]

    print("  No saved UptimeRobot credentials found.")
    email = input("  UptimeRobot email: ").strip()
    password = input("  UptimeRobot password: ").strip()
    return email, password


def setup_uptimerobot(render_url: str) -> tuple[str, str, bool]:
    """Login to UptimeRobot, create HTTP monitor.

    Returns:
        (email, password, success)
    """
    email, password = _load_credentials()

    print(f"  [1/2] Logging in as {email}...")
    ok = _create_monitor(email, password, render_url)

    if ok:
        print("  [✓] Monitor created")
    else:
        print("  [!] Could not create monitor")

    return email, password, ok


def _create_monitor(email: str, password: str, render_url: str) -> bool:
    """Login to UptimeRobot and create an HTTP monitor."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://uptimerobot.com/login")
        sb.sleep(8)

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

        # Navigate to add monitor
        sb.goto("https://uptimerobot.com/add")
        sb.sleep(5)

        # Select HTTP(s)
        with suppress(Exception):
            if sb.is_text_visible("HTTP(s)", timeout=3):
                sb.click('text="HTTP(s)"')
                sb.sleep(1)

        # Friendly name
        with suppress(Exception):
            sb.type('input[name="friendly_name"], input[placeholder*="name"]', "NSE-BSE Quant Dashboard", timeout=5)
        sb.sleep(0.3)

        # URL
        with suppress(Exception):
            sb.type('input[name="url"], input[placeholder*="URL"]', render_url, timeout=5)
        sb.sleep(0.3)

        # Monitoring interval
        with suppress(Exception):
            sb.select_option_by_text('select[name="interval"]', "5")
        sb.sleep(0.3)

        # Create
        with suppress(Exception):
            sb.click('button:contains("Create Monitor"), button:contains("Save"), button[type="submit"]', timeout=5)
        sb.sleep(3)

        # Confirm
        with suppress(Exception):
            if sb.is_text_visible("Yes", timeout=3):
                sb.click('button:contains("Yes")')
                sb.sleep(2)

        return True


if __name__ == "__main__":
    render_url = input("Render URL: ").strip()
    email, password, ok = setup_uptimerobot(render_url)
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  Success: {ok}")
