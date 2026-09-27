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


"""Neon PostgreSQL setup — Phase 2: Login + create project + extract DSN.

Reads credentials from accounts.json (created by create_accounts.py).
Uses saved cookies for session reuse.
"""


import json
import re
from contextlib import suppress
from pathlib import Path

from seleniumbase import SB

COOKIES_FILE = Path(__file__).parent / ".cookies_neon.txt"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"


def _load_credentials() -> tuple[str, str]:
    """Load Neon credentials from accounts.json."""
    if ACCOUNTS_FILE.exists():
        accounts = json.loads(ACCOUNTS_FILE.read_text())
        if "neon" in accounts:
            return accounts["neon"]["email"], accounts["neon"]["password"]

    # Fallback: ask user
    print("  No saved Neon credentials found.")
    email = input("  Neon email: ").strip()
    password = input("  Neon password: ").strip()
    return email, password


def setup_neon(project_name: str = "nse-bse-quant") -> tuple[str, str, str]:
    """Login to Neon, create project, extract DSN.

    Returns:
        (email, password, connection_string)
    """
    email, password = _load_credentials()

    print(f"  [1/3] Logging in as {email}...")
    neon_dsn = _create_project(email, password, project_name)

    if neon_dsn:
        print("  [✓] DSN obtained")
    else:
        print("  [!] Could not extract DSN")

    return email, password, neon_dsn


def _create_project(email: str, password: str, project_name: str) -> str:
    """Login to Neon, create/select project, return connection string."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://console.neon.tech/signin")
        sb.sleep(10)

        # Login if needed
        current_url = sb.get_current_url()
        if "signin" in current_url or "realms" in current_url:
            with suppress(Exception):
                sb.type('input[name="email"]', email, timeout=5)
                sb.sleep(0.3)
            with suppress(Exception):
                sb.type('input[name="password"]', password, timeout=3)
                sb.sleep(0.3)
            with suppress(Exception):
                sb.click('button:contains("Continue"), button[type="submit"]', timeout=5)
            sb.sleep(10)

        sb.save_cookies(str(COOKIES_FILE))

        # Go to projects
        sb.goto("https://console.neon.tech/app/projects")
        sb.sleep(5)

        # Check if project exists
        if sb.is_text_visible(project_name):
            sb.click(f'text="{project_name}"')
            sb.sleep(3)
        else:
            # Create project
            with suppress(Exception):
                sb.click('button:contains("Create project"), a:contains("Create project")', timeout=5)
            with suppress(Exception):
                sb.click('a[href*="create"], button:contains("New")', timeout=3)
            sb.sleep(2)

            with suppress(Exception):
                name_input = sb.find_element('input[name="name"], input[placeholder*="project"]', timeout=5)
                name_input.clear()
                sb.type('input[name="name"], input[placeholder*="project"]', project_name)
                sb.sleep(0.5)

            with suppress(Exception):
                sb.click('button:contains("Create"), button[type="submit"]', timeout=5)
            sb.sleep(5)

        return _extract_connection_string(sb)


def _extract_connection_string(sb: SB) -> str:
    """Extract PostgreSQL connection string from Neon dashboard."""
    with suppress(Exception):
        sb.click('button:contains("Connect"), [data-testid="connect-button"]', timeout=5)
        sb.sleep(2)

    selectors = [
        "code",
        "pre",
        ".connection-string",
        '[class*="connection"]',
        "[data-clipboard-text]",
        "input[readonly]",
    ]

    for sel in selectors:
        with suppress(Exception):
            elements = sb.find_elements(sel)
            for el in elements:
                txt = el.get_attribute("data-clipboard-text") or el.text or el.get_attribute("value") or ""
                if "postgresql://" in txt:
                    return txt.strip()

    source = sb.get_page_source()
    match = re.search(r'postgresql://[^\s"<>\'&]+', source)
    if match:
        return match.group(0)

    return ""


def verify_neon_connection(dsn: str) -> bool:
    """Quick verify the Neon connection string works."""
    try:
        import sqlalchemy as sa

        engine = sa.create_engine(dsn, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(sa.text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        print(f"  [!] Neon connection failed: {e}")
        return False


if __name__ == "__main__":
    email, password, dsn = setup_neon()
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  DSN: {dsn}")
