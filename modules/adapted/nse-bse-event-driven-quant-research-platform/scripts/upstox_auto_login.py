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


#!/usr/bin/env python3
"""Automated Upstox OAuth2 login with Gmail OTP reading.

Actual Upstox web OAuth flow (discovered via Playwright inspection):
  1. Navigate to OAuth URL → redirects to login.upstox.com
  2. Enter 10-digit mobile number → click "Get OTP"
  3. OTP sent via SMS + email
  4. Enter OTP → auto-submits or click submit
  5. Redirect to redirect_uri with ?code=...
  6. Exchange code for tokens

Usage:
  python scripts/upstox_auto_login.py              # headless (default)
  python scripts/upstox_auto_login.py --headed     # visible browser (debug)
  python scripts/upstox_auto_login.py --check      # just check token status
  python scripts/upstox_auto_login.py --force      # force refresh even if valid
"""


import argparse
import base64
import contextlib
import email
import email.utils
import imaplib
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from datetime import UTC, datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TOKEN_FILE = ROOT / "upstox_tokens.json"
ENV_FILE = ROOT / ".env"
LOG_DIR = ROOT / "logs"

LOGIN_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
PROFILE_URL = "https://api.upstox.com/v2/user/profile"

log = logging.getLogger("upstox_auto")


# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------


def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


def get_env() -> dict[str, str]:
    merged = {**load_dotenv(), **os.environ}
    required = {
        "UPSTOX_API_KEY": merged.get("UPSTOX_API_KEY", ""),
        "UPSTOX_API_SECRET": merged.get("UPSTOX_API_SECRET", ""),
        "UPSTOX_REDIRECT_URI": merged.get("UPSTOX_REDIRECT_URI", ""),
        "UPSTOX_MOBILE": merged.get("UPSTOX_MOBILE", ""),
        "UPSTOX_PIN": merged.get("UPSTOX_PIN", "") or merged.get("UPSTOX_PASSWORD", ""),
        "GMAIL_ADDRESS": merged.get("GMAIL_ADDRESS", ""),
        "GMAIL_APP_PASSWORD": merged.get("GMAIL_APP_PASSWORD", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        msg = f"Missing env vars: {', '.join(missing)}"
        raise SystemExit(msg)
    return required


def save_tokens(payload: dict) -> None:
    """Save token payload to upstox_tokens.json and update .env."""
    existing = {}
    if TOKEN_FILE.exists():
        with contextlib.suppress(Exception):
            existing = json.loads(TOKEN_FILE.read_text())
    merged = {**existing, **payload}
    TOKEN_FILE.write_text(json.dumps(merged, indent=2))
    log.info("Saved tokens to %s", TOKEN_FILE)

    access_token = payload.get("access_token", "")
    if access_token:
        _update_env("UPSTOX_ACCESS_TOKEN", access_token)


def _update_env(key: str, value: str) -> None:
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Gmail IMAP — read latest OTP email
# ---------------------------------------------------------------------------


def read_otp_from_gmail(
    address: str, app_password: str, timeout_s: int = 90, since_time: float | None = None
) -> str | None:
    """Poll Gmail IMAP for an Upstox OTP email. Returns 6-digit code or None.

    Args:
        since_time: If provided, only consider emails received after this timestamp.
                    This prevents reusing OTPs from previous login attempts.
    """
    log.info(
        "Polling Gmail for Upstox OTP (timeout=%ds, since=%s)...",
        timeout_s,
        datetime.fromtimestamp(since_time).strftime("%H:%M:%S") if since_time else "any",
    )
    deadline = time.time() + timeout_s
    seen_ids: set[bytes] = set()

    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(address, app_password)
            mail.select("INBOX")

            # Search specifically for Upstox emails from today
            today = datetime.now().strftime("%d-%b-%Y")
            criteria = f'(SINCE "{today}" FROM "upstox.com")'
            status, data = mail.search(None, criteria)
            if status != "OK":
                mail.logout()
                time.sleep(5)
                continue

            msg_ids = data[0].split()
            if not msg_ids:
                # Broader search: FROM "upstox" (no domain)
                criteria = f'(SINCE "{today}" FROM "upstox")'
                status, data = mail.search(None, criteria)
                if status == "OK":
                    msg_ids = data[0].split()

            if not msg_ids:
                mail.logout()
                log.debug("No Upstox emails yet, retrying...")
                time.sleep(5)
                continue

            # Check the LATEST email only (most likely to be the fresh OTP)
            latest_id = msg_ids[-1]
            if latest_id in seen_ids:
                mail.logout()
                time.sleep(5)
                continue
            seen_ids.add(latest_id)

            status, msg_data = mail.fetch(latest_id, "(RFC822)")
            if status != "OK":
                mail.logout()
                time.sleep(5)
                continue

            raw_email = msg_data[0][1]
            if isinstance(raw_email, bytes):
                raw_email = raw_email.decode("utf-8", errors="replace")

            # Check email date against since_time
            if since_time:
                try:
                    msg = email.message_from_string(raw_email)
                    date_str = msg.get("Date", "")
                    # Parse email date: "Mon, 7 Sep 2026 13:00:19 +0530 (IST)"
                    from email.utils import parsedate_to_datetime

                    email_dt = parsedate_to_datetime(date_str)
                    email_ts = email_dt.timestamp()
                    if email_ts <= since_time:
                        log.debug("  Email too old (%s), skipping", email_dt.strftime("%H:%M:%S"))
                        mail.logout()
                        time.sleep(5)
                        continue
                except Exception as e:
                    log.debug("  Could not parse email date: %s", e)

            # Extract OTP from this specific email
            otp = _extract_otp_from_upstox_email(raw_email)
            if otp:
                log.info("Found OTP: %s", otp)
                mail.logout()
                return otp

            log.debug("Latest Upstox email doesn't contain OTP, retrying...")
            mail.logout()
            time.sleep(5)

        except imaplib.IMAP4.error as e:
            log.warning("Gmail IMAP error: %s", e)
            time.sleep(10)
        except Exception as e:
            log.warning("Gmail read error: %s", e)
            time.sleep(10)

    log.error("OTP not found in Gmail after %ds", timeout_s)
    return None


def _extract_otp_from_upstox_email(email_body: str) -> str | None:
    """Extract OTP specifically from Upstox OTP email."""
    # Strip HTML tags for cleaner extraction
    clean = re.sub(r"<[^>]+>", " ", email_body)
    clean = re.sub(r"\s+", " ", clean).strip()

    # Upstox OTP emails: "please input the code below to continue. 381095"
    patterns = [
        r"(?:OTP|otp|code|Code)[^\d]*(\d{6})",  # "code: 123456" or "OTP is 123456"
        r"(\d{6})\s*(?:is|is your|your)",  # "123456 is your OTP"
        r"(?:is|your)\s+(\d{6})",  # "is 123456"
    ]
    for pattern in patterns:
        matches = re.findall(pattern, clean)
        if matches:
            return matches[-1]

    # Fallback: look for 6-digit number in HTML tags (>381095<)
    html_matches = re.findall(r">\s*(\d{6})\s*<", email_body)
    if html_matches:
        return html_matches[-1]

    # Last resort: any 6-digit number
    all_matches = re.findall(r"\b(\d{6})\b", clean)
    if all_matches:
        return all_matches[-1]

    return None


# ---------------------------------------------------------------------------
# Playwright browser automation
# ---------------------------------------------------------------------------


def run_login_flow(headed: bool = False) -> dict | None:
    """Full Upstox OAuth login flow. Returns token payload or None on failure."""
    env = get_env()
    api_key = env["UPSTOX_API_KEY"]
    api_secret = env["UPSTOX_API_SECRET"]
    redirect_uri = env["UPSTOX_REDIRECT_URI"]
    mobile = env["UPSTOX_MOBILE"]
    pin = env["UPSTOX_PIN"]
    gmail_addr = env["GMAIL_ADDRESS"]
    gmail_pass = env["GMAIL_APP_PASSWORD"]

    # Build login URL
    login_url = (
        f"{LOGIN_URL}?response_type=code&client_id={api_key}&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
    )
    log.info("Login URL: %s", login_url[:120] + "...")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        try:
            # Step 1: Navigate to Upstox OAuth
            log.info("[1] Navigating to Upstox OAuth...")
            page.goto(login_url, timeout=60000, wait_until="domcontentloaded")

            # Step 2: Wait for Cloudflare if present
            log.info("[2] Waiting for Cloudflare...")
            for i in range(30):
                title = page.title()
                if "just a moment" not in title.lower() and "checking" not in title.lower():
                    break
                time.sleep(2)
                if i % 5 == 0:
                    log.debug("  CF wait: %s", title)
            time.sleep(2)

            # Step 3: Wait for mobile number input and fill it
            log.info("[3] Looking for mobile number input...")
            _screenshot(page, "step3_before_mobile")

            mobile_input = _wait_for_selector(
                page,
                [
                    "#mobileNum",
                    'input[placeholder*="10 digit" i]',
                    'input[placeholder*="mobile" i]',
                    'input[maxlength="10"]',
                ],
                timeout=15,
            )

            if not mobile_input:
                log.error("  Cannot find mobile number input")
                _screenshot(page, "error_no_mobile_input")
                _dump_page_info(page)
                return None

            mobile_input.click()
            mobile_input.fill(mobile)
            log.info("  Filled mobile: %s", mobile[:3] + "****" + mobile[-2:])
            time.sleep(0.5)

            _screenshot(page, "step3_mobile_filled")

            # Step 4: Click "Get OTP" button
            log.info("[4] Clicking 'Get OTP'...")
            get_otp_btn = _wait_for_selector(
                page,
                [
                    "#getOtp",
                    'button:has-text("Get OTP")',
                    'button:has-text("Get otp")',
                    'button[type="submit"]',
                ],
                timeout=10,
            )

            if not get_otp_btn:
                log.error("  Cannot find 'Get OTP' button")
                _screenshot(page, "error_no_get_otp_btn")
                return None

            # Wait for button to be enabled
            for _ in range(10):
                disabled = get_otp_btn.get_attribute("disabled")
                if disabled is None:
                    break
                time.sleep(0.5)

            get_otp_btn.click()
            log.info("  Clicked 'Get OTP'")
            time.sleep(3)

            _screenshot(page, "step4_after_get_otp")

            # Step 5: Wait for OTP input field to appear
            log.info("[5] Waiting for OTP input field...")
            otp_input = None
            for i in range(30):
                time.sleep(2)

                # Check for redirect (might skip OTP if session is cached)
                code = _extract_code_from_url(page.url)
                if code:
                    log.info("  Got code directly — no OTP needed!")
                    return _exchange_and_save(code, api_key, api_secret, redirect_uri)

                # Look for OTP input
                otp_input = _find_otp_input(page)
                if otp_input:
                    log.info("  OTP input found at iteration %d", i)
                    break

                if i % 5 == 0:
                    log.debug("  Waiting for OTP input: %s", page.url[:80])

            _screenshot(page, "step5_otp_page")

            if not otp_input:
                # Check if we got redirected
                code = _extract_code_from_url(page.url)
                if code:
                    log.info("  Got code from redirect (no OTP)")
                    return _exchange_and_save(code, api_key, api_secret, redirect_uri)

                log.error("  OTP input not found and no redirect")
                _dump_page_info(page)
                return None

            # Step 6: Read OTP from Gmail (only consider emails after current token issue time)
            log.info("[6] Reading OTP from Gmail...")
            since_time = _get_token_issue_time()
            otp = read_otp_from_gmail(gmail_addr, gmail_pass, timeout_s=90, since_time=since_time)
            if not otp:
                log.error("  Failed to read OTP from Gmail")
                _screenshot(page, "error_no_otp")
                return None

            # Step 7: Fill OTP
            log.info("[7] Filling OTP: %s", otp)
            otp_input.click()
            otp_input.fill(otp)
            log.info("  Filled OTP")
            time.sleep(1)

            _screenshot(page, "step7_otp_filled")

            # Step 8: Submit OTP (click verify/submit button or press Enter)
            log.info("[8] Submitting OTP...")
            time.sleep(1)  # Wait for Continue button to enable

            # Wait for #continueBtn to become enabled
            submit_btn = None
            for _ in range(10):
                btn = _wait_for_selector(
                    page,
                    [
                        "#continueBtn",
                        'button:has-text("Verify")',
                        'button:has-text("Submit")',
                        'button:has-text("Continue")',
                        'button[type="submit"]',
                    ],
                    timeout=3,
                )
                if btn:
                    disabled = btn.get_attribute("disabled")
                    if disabled is None:
                        submit_btn = btn
                        break
                time.sleep(0.5)

            if submit_btn:
                submit_btn.click()
                log.info("  Clicked submit button")
            else:
                otp_input.press("Enter")
                log.info("  Pressed Enter to submit")

            # Step 9: Wait for redirect OR PIN page
            log.info("[9] Waiting for redirect or PIN page...")
            code = None
            for i in range(40):
                time.sleep(2)
                current_url = page.url

                code = _extract_code_from_url(current_url)
                if code:
                    log.info("  Got authorization code!")
                    break

                # Check for PIN page (with error handling for navigation)
                try:
                    body_text = page.evaluate("document.body.innerText.substring(0,500)")
                except Exception:
                    # Page is navigating — check URL for code
                    time.sleep(2)
                    code = _extract_code_from_url(page.url)
                    if code:
                        log.info("  Got code after navigation!")
                    break

                if "pin" in body_text.lower() and ("enter" in body_text.lower() or "6-digit" in body_text.lower()):
                    log.info("  PIN page detected!")
                    _screenshot(page, "step9a_pin_page")

                    # Find PIN input
                    pin_input = _wait_for_selector(
                        page,
                        [
                            "#pinInput",
                            "#pin",
                            'input[name="pin"]',
                            'input[type="password"]',
                            'input[type="tel"]',
                            'input[maxlength="6"]',
                            'input[placeholder*="PIN" i]',
                        ],
                        timeout=10,
                    )

                    if not pin_input:
                        pin_input = _find_otp_input(page)

                    if pin_input:
                        pin_input.click()
                        pin_input.fill(pin)
                        log.info("  Filled PIN: ****")
                        time.sleep(1)

                        # Click Continue
                        pin_btn = _wait_for_selector(
                            page,
                            [
                                "#continueBtn",
                                'button:has-text("Continue")',
                                'button[type="submit"]',
                            ],
                            timeout=5,
                        )
                        if pin_btn:
                            for _ in range(10):
                                disabled = pin_btn.get_attribute("disabled")
                                if disabled is None:
                                    break
                                time.sleep(0.5)
                            pin_btn.click()
                            log.info("  Clicked Continue after PIN")
                        else:
                            pin_input.press("Enter")
                            log.info("  Pressed Enter after PIN")

                        _screenshot(page, "step9b_after_pin")
                        # Wait for navigation to complete
                        time.sleep(5)
                        # Check URL immediately after navigation
                        code = _extract_code_from_url(page.url)
                        if code:
                            log.info("  Got code after PIN navigation!")
                            break
                    else:
                        log.error("  Cannot find PIN input")
                        _dump_page_info(page)
                    continue

                # Check for ngrok interstitial page
                if "ngrok" in current_url and "code=" not in current_url:
                    try:
                        body = page.evaluate("document.body.innerText")
                        code_match = re.search(r'[?&]code=([^\s&"]+)', body)
                        if code_match:
                            code = code_match.group(1)
                            log.info("  Got code from ngrok interstitial")
                            break
                    except Exception:
                        pass

                if i % 5 == 0:
                    log.debug("  Waiting: %s", current_url[:100])

            _screenshot(page, "step9_final")

            if not code:
                log.error("  No authorization code found")
                log.error("  Final URL: %s", page.url[:200])
                _dump_page_info(page)
                return None

            # Step 10: Exchange code for tokens
            log.info("[10] Exchanging code for tokens...")
            return _exchange_and_save(code, api_key, api_secret, redirect_uri)

        except Exception as e:
            log.error("Login flow error: %s", e, exc_info=True)
            with contextlib.suppress(Exception):
                _screenshot(page, "error_exception")
            return None
        finally:
            browser.close()


def _wait_for_selector(page, selectors: list[str], timeout: int = 10):
    """Try multiple selectors, return first visible match."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return el
            except Exception:
                continue
        time.sleep(0.5)
    return None


def _find_otp_input(page):
    """Find the OTP input field using multiple strategies."""
    # Strategy 1: known selectors (Upstox uses #otpNum)
    for sel in [
        "#otpNum",
        "#otp",
        "#otpInput",
        'input[name="otp"]',
        'input[placeholder*="OTP" i]',
        'input[placeholder*="code" i]',
        'input[maxlength="6"]',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            continue

    # Strategy 2: find visible empty input (after mobile was filled, OTP input is new)
    try:
        inputs = page.query_selector_all(
            'input[type="text"], input[type="tel"], input[type="number"], input:not([type])'
        )
        for inp in inputs:
            try:
                if inp.is_visible():
                    val = inp.input_value()
                    if not val:
                        ml = inp.get_attribute("maxlength")
                        if ml and int(ml) <= 8:
                            return inp
            except Exception:
                continue
    except Exception:
        pass

    return None


def _extract_code_from_url(url: str) -> str | None:
    """Extract authorization code from redirect URL."""
    match = re.search(r"[?&]code=([^\s&]+)", url)
    if match:
        return match.group(1)
    return None


def _get_token_issue_time() -> float | None:
    """Get the issue time of the current access token (for Gmail filtering)."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        access_token = data.get("access_token", "")
        if not access_token:
            return None
        parts = access_token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return decoded.get("iat", 0)
    except Exception:
        return None


def _exchange_and_save(code: str, api_key: str, api_secret: str, redirect_uri: str) -> dict | None:
    """Exchange authorization code for tokens and save."""
    log.info("Exchanging code for tokens...")
    try:
        resp = httpx.post(
            TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "code": code,
                "client_id": api_key,
                "client_secret": api_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            log.error("Token exchange failed (%d): %s", resp.status_code, resp.text[:300])
            return None

        payload = resp.json()
        log.info("Token exchange OK — access_token length: %d", len(payload.get("access_token", "")))
        save_tokens(payload)
        return payload

    except Exception as e:
        log.exception("Token exchange error: %s", e)
        return None


def _screenshot(page, name: str) -> None:
    """Save screenshot for debugging."""
    try:
        ss_dir = LOG_DIR / "screenshots"
        ss_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ss_dir / f"upstox_{name}.png"))
        log.debug("Screenshot: %s", name)
    except Exception as e:
        log.debug("Screenshot failed: %s", e)


def _dump_page_info(page) -> None:
    """Dump page info for debugging."""
    try:
        url = page.url
        title = page.title()
        log.info("  Page: title=%s url=%s", title[:60], url[:120])

        inputs = page.evaluate("""
            Array.from(document.querySelectorAll('input, button, select, textarea'))
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    disabled: el.disabled,
                    text: el.innerText?.substring(0, 50) || '',
                }))
        """)
        log.info("  Visible elements: %s", json.dumps(inputs[:15], indent=2))
    except Exception as e:
        log.debug("Page dump failed: %s", e)


# ---------------------------------------------------------------------------
# Token status check
# ---------------------------------------------------------------------------


def check_token_status() -> dict:
    """Check current token status."""
    result = {"valid": False, "expires": None, "remaining_hours": None}
    if not TOKEN_FILE.exists():
        result["error"] = "No token file"
        return result

    try:
        data = json.loads(TOKEN_FILE.read_text())
    except Exception as e:
        result["error"] = str(e)
        return result

    access_token = data.get("access_token", "")
    if not access_token:
        result["error"] = "No access_token"
        return result

    try:
        parts = access_token.split(".")
        if len(parts) >= 2:
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            exp = decoded.get("exp", 0)
            now = time.time()
            remaining_h = (exp - now) / 3600
            result["expires"] = datetime.fromtimestamp(exp, tz=UTC).isoformat()
            result["remaining_hours"] = round(remaining_h, 1)
            result["valid"] = remaining_h > 0
            result["user_id"] = decoded.get("sub", "")
    except Exception as e:
        result["error"] = f"JWT decode failed: {e}"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Upstox automated OAuth login")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--check", action="store_true", help="Check token status only")
    parser.add_argument("--force", action="store_true", help="Force refresh even if token valid")
    parser.add_argument("--retries", type=int, default=3, help="Number of retry attempts")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "upstox_auth.log"),
        ],
    )

    if args.check:
        status = check_token_status()
        print(json.dumps(status, indent=2))
        return 0 if status["valid"] else 1

    # Check if token is still valid
    status = check_token_status()
    if status.get("remaining_hours", 0) > 2 and not args.force:
        log.info("Token still valid for %.1f hours — skipping refresh", status["remaining_hours"])
        print(json.dumps(status, indent=2))
        return 0

    # Run login flow with retries
    for attempt in range(1, args.retries + 1):
        log.info("=" * 60)
        log.info("ATTEMPT %d/%d", attempt, args.retries)
        log.info("=" * 60)

        result = run_login_flow(headed=args.headed)
        if result:
            log.info("SUCCESS — token refreshed")
            profile = _verify_token(result.get("access_token", ""))
            if profile:
                log.info("Verified: %s", json.dumps(profile, indent=2))
            return 0

        log.warning("Attempt %d failed", attempt)
        if attempt < args.retries:
            log.info("Waiting 5 minutes before retry...")
            time.sleep(300)

    log.error("All %d attempts failed", args.retries)
    return 1


def _verify_token(token: str) -> dict | None:
    """Verify token via /v2/user/profile."""
    try:
        resp = httpx.get(
            PROFILE_URL,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data:
                d = data["data"]
                return {
                    "user_id": d.get("user_id"),
                    "user_name": d.get("user_name"),
                    "email": d.get("email"),
                    "broker": d.get("broker"),
                }
        log.warning("Profile check failed: %d %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("Profile check error: %s", e)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
