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


"""Render web service setup — Phase 2: Login + create Docker service + deploy.

Reads credentials from accounts.json (created by create_accounts.py).
Uses saved cookies for session reuse.
"""


import json
from contextlib import suppress
from pathlib import Path

from seleniumbase import SB

COOKIES_FILE = Path(__file__).parent / ".cookies_render.txt"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"
REPO_URL = "https://github.com/kondaiahpola1-wq/NSE-BSE-Event-Driven-Quant-Research-Platform"


def _load_credentials() -> tuple[str, str]:
    """Load Render credentials from accounts.json."""
    if ACCOUNTS_FILE.exists():
        accounts = json.loads(ACCOUNTS_FILE.read_text())
        if "render" in accounts:
            return accounts["render"]["email"], accounts["render"]["password"]

    print("  No saved Render credentials found.")
    email = input("  Render email: ").strip()
    password = input("  Render password: ").strip()
    return email, password


def setup_render(
    pg_dsn: str,
    redis_url: str,
    service_name: str = "nse-bse-quant",
) -> tuple[str, str, str]:
    """Login to Render, create Docker web service, set env vars.

    Returns:
        (email, password, render_url)
    """
    email, password = _load_credentials()

    print(f"  [1/3] Logging in as {email}...")
    render_url = _create_web_service(email, password, service_name)

    if render_url:
        print(f"  [✓] Service created: {render_url}")
        print("  [2/3] Setting environment variables...")
        _set_env_vars(email, password, pg_dsn, redis_url, service_name)
    else:
        print("  [!] Could not create web service")

    return email, password, render_url or ""


def _create_web_service(email: str, password: str, service_name: str) -> str:
    """Login to Render and create a Docker web service."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://dashboard.render.com/signin")
        sb.sleep(8)

        current_url = sb.get_current_url()
        if "signin" in current_url:
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

        # New web service
        sb.goto("https://dashboard.render.com/new?type=web")
        sb.sleep(5)

        # Build from Git
        with suppress(Exception):
            sb.click('text="Build and deploy from a Git repository"', timeout=5)
        sb.sleep(1)
        with suppress(Exception):
            sb.click('button:contains("Next"), button:contains("Continue")', timeout=5)
        sb.sleep(2)

        # Connect repo
        with suppress(Exception):
            if sb.is_text_visible("kondaiahpola1-wq", timeout=3):
                sb.click('text="kondaiahpola1-wq"')
                sb.sleep(1)
            else:
                sb.click(
                    'button:contains("Connect a repository"), a:contains("Connect")', timeout=5
                )
                sb.sleep(3)
                sb.click('text*="NSE-BSE-Event-Driven"', timeout=5)
                sb.sleep(1)

        with suppress(Exception):
            sb.click('button:contains("Next"), button:contains("Continue")', timeout=5)
        sb.sleep(2)

        # Set service name
        with suppress(Exception):
            name_input = sb.find_element(
                'input[name="name"], input[placeholder*="name"]', timeout=5
            )
            name_input.clear()
            sb.type('input[name="name"], input[placeholder*="name"]', service_name)
        sb.sleep(0.5)

        # Region
        with suppress(Exception):
            sb.select_option_by_text('select[name="region"]', "Singapore")
        sb.sleep(0.5)

        # Plan: Free
        with suppress(Exception):
            if sb.is_text_visible("Free", timeout=3):
                sb.click('text="Free"')
        sb.sleep(0.5)

        # Dockerfile path
        with suppress(Exception):
            sb.type('input[name="dockerfilePath"], input[placeholder*="Docker"]', "./Dockerfile")
        sb.sleep(0.5)

        # Create service
        with suppress(Exception):
            sb.click('button:contains("Create Web Service"), button:contains("Deploy")', timeout=5)
        sb.sleep(8)

        return f"https://{service_name}.onrender.com"


def _set_env_vars(
    email: str, password: str, pg_dsn: str, redis_url: str, service_name: str
) -> None:
    """Set environment variables on the Render service."""
    env_vars = {
        "NSE_QUANT_PG_DSN": pg_dsn,
        "NSE_QUANT_REDIS_URL": redis_url,
        "REDIS_TTL": "3600",
    }

    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto(f"https://dashboard.render.com/web/{service_name}/env")
        sb.sleep(5)

        for key, value in env_vars.items():
            with suppress(Exception):
                sb.click(
                    'button:contains("Add Environment Variable"), button:contains("Add")', timeout=5
                )
                sb.sleep(1)

                inputs = sb.find_elements('input[placeholder*="Key"], input[name*="key"]')
                if inputs:
                    inputs[0].clear()
                    sb.send_keys(inputs[0], key)

                val_inputs = sb.find_elements('input[placeholder*="Value"], input[name*="value"]')
                if val_inputs:
                    val_inputs[0].clear()
                    sb.send_keys(val_inputs[0], value)

                sb.click('button:contains("Save"), button:contains("Add")', timeout=3)
                sb.sleep(1)
                print(f"  [✓] Set {key}")

    # Trigger deploy
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto(f"https://dashboard.render.com/web/{service_name}/events")
        sb.sleep(5)

        with suppress(Exception):
            if sb.is_text_visible("Manual Deploy", timeout=5):
                sb.click('button:contains("Manual Deploy")')
                sb.sleep(1)
                sb.click('text*="Deploy latest commit"')
                sb.sleep(3)
                print("  [✓] Deploy triggered")


if __name__ == "__main__":
    pg_dsn = input("Neon DSN: ").strip()
    redis_url = input("Redis URL: ").strip()
    email, password, url = setup_render(pg_dsn, redis_url)
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  URL: {url}")
