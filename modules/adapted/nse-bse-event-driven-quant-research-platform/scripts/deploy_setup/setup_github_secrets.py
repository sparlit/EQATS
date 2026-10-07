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


"""GitHub secrets setup — Phase 2: Login + create PAT + set repo secrets.

Reads credentials from accounts.json (created by create_accounts.py).
Uses saved cookies for session reuse.
"""


import base64
import json
import re
from contextlib import suppress
from pathlib import Path

import httpx
from nacl import public
from seleniumbase import SB

COOKIES_FILE = Path(__file__).parent / ".cookies_github.txt"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"
REPO = "kondaiahpola1-wq/NSE-BSE-Event-Driven-Quant-Research-Platform"
API_BASE = "https://api.github.com"


def _load_credentials() -> tuple[str, str]:
    """Load GitHub credentials from accounts.json."""
    if ACCOUNTS_FILE.exists():
        accounts = json.loads(ACCOUNTS_FILE.read_text())
        if "github" in accounts:
            return accounts["github"]["email"], accounts["github"]["password"]

    print("  No saved GitHub credentials found.")
    email = input("  GitHub email: ").strip()
    password = input("  GitHub password: ").strip()
    return email, password


def setup_github_secrets(neon_dsn: str, redis_url: str) -> tuple[str, str, bool]:
    """Login to GitHub, create PAT, set repo secrets.

    Returns:
        (email, password, success)
    """
    email, password = _load_credentials()

    print(f"  [1/3] Logging in as {email}...")
    pat = _create_pat(email, password)

    if not pat:
        print("  [!] Could not create PAT")
        return email, password, False

    print(f"  [✓] PAT created: {pat[:12]}...")

    print("  [2/3] Setting repository secrets...")
    ok = _set_repo_secrets(pat, neon_dsn, redis_url)

    return email, password, ok


def _create_pat(email: str, password: str) -> str:
    """Login to GitHub and create a Personal Access Token."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://github.com/login")
        sb.sleep(5)

        current_url = sb.get_current_url()
        if "login" in current_url:
            with suppress(Exception):
                sb.type('input[type="text"], input[name="login"]', email, timeout=5)
                sb.sleep(0.3)
            with suppress(Exception):
                sb.type('input[type="password"], input[name="password"]', password, timeout=3)
                sb.sleep(0.3)
            with suppress(Exception):
                sb.click('input[type="submit"], button:contains("Sign in")', timeout=5)
            sb.sleep(8)

        sb.save_cookies(str(COOKIES_FILE))

        # Go to token settings
        sb.goto("https://github.com/settings/tokens?type=beta")
        sb.sleep(5)

        # Generate new token
        with suppress(Exception):
            sb.click(
                'button:contains("Generate new token"), a:contains("Generate new token")', timeout=5
            )
        sb.sleep(2)

        # Note
        with suppress(Exception):
            sb.type(
                'input[name="name"], input[placeholder*="note"]', "nse-bse-quant-deploy", timeout=5
            )
        sb.sleep(0.3)

        # Expiration
        with suppress(Exception):
            sb.select_option_by_text('select[name="expiration"]', "90 days")
        sb.sleep(0.3)

        # Select repo scope
        with suppress(Exception):
            sb.click('text="repo"', timeout=3)
        sb.sleep(0.3)

        # Generate
        with suppress(Exception):
            sb.click('button:contains("Generate token"), button[type="submit"]', timeout=5)
        sb.sleep(3)

        # Extract token
        with suppress(Exception):
            token_el = sb.find_element("code, [data-clipboard-text], input[readonly]", timeout=5)
            if token_el:
                pat = (
                    token_el.get_attribute("data-clipboard-text")
                    or token_el.text
                    or token_el.get_attribute("value")
                    or ""
                )
                if pat.startswith("ghp_") or pat.startswith("github_pat_"):
                    return pat.strip()

        # Regex fallback
        source = sb.get_page_source()
        match = re.search(r"(ghp_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})", source)
        if match:
            return match.group(1)

    return ""


def _set_repo_secrets(pat: str, neon_dsn: str, redis_url: str) -> bool:
    """Set repository secrets using GitHub API + NaCl encryption."""
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}

    r = httpx.get(f"{API_BASE}/repos/{REPO}/actions/secrets/public-key", headers=headers)
    if r.status_code != 200:
        print(f"  [!] Failed to get repo public key: {r.status_code}")
        return False

    key_data = r.json()
    key_b64 = key_data["key"]
    key_id = key_data["key_id"]

    repo_key = public.PublicKey(base64.b64decode(key_b64), encoder=public.Encoder.BOX)
    sealed_box = public.SealedBox(repo_key)

    secrets = {
        "NEON_PG_DSN": neon_dsn,
        "UPSTASH_REDIS_URL": redis_url,
    }

    all_ok = True
    for secret_name, secret_value in secrets.items():
        encrypted = base64.b64encode(sealed_box.encrypt(secret_value.encode())).decode()

        r = httpx.put(
            f"{API_BASE}/repos/{REPO}/actions/secrets/{secret_name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id},
        )

        if r.status_code in (200, 204):
            print(f"  [✓] Secret {secret_name} set")
        else:
            print(f"  [!] Failed to set {secret_name}: {r.status_code}")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    neon_dsn = input("Neon DSN: ").strip()
    redis_url = input("Redis URL: ").strip()
    email, password, ok = setup_github_secrets(neon_dsn, redis_url)
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  Success: {ok}")
