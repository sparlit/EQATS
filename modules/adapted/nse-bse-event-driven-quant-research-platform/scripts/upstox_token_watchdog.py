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
"""Upstox token watchdog — checks token validity and refreshes if expiring soon.

Designed to run frequently (every 5-30 min) via cron or health_check.
If token expires within THRESHOLD_MINUTES, triggers full auto-login.

Usage:
  python scripts/upstox_token_watchdog.py           # check & refresh if needed
  python scripts/upstox_token_watchdog.py --threshold 30  # custom threshold
"""


import argparse
import base64
import contextlib
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "upstox_tokens.json"
LOG_DIR = ROOT / "logs"
BROWSING_VENV = Path("/home/ubuntu/Documents/projects/projects_agn/Browsing/venv/bin/python")
AUTO_LOGIN_SCRIPT = ROOT / "scripts" / "upstox_auto_login.py"

THRESHOLD_MINUTES = 5  # refresh if less than this many minutes remaining
LOCK_FILE = LOG_DIR / ".upstox_refresh.lock"

log = logging.getLogger("upstox_watchdog")


def get_token_remaining_minutes() -> float | None:
    """Return minutes until access token expires, or None if no token."""
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
        exp = decoded.get("exp", 0)
        now = time.time()
        return (exp - now) / 60
    except Exception:
        return None


def acquire_lock() -> bool:
    """Acquire refresh lock (prevent concurrent refreshes)."""
    try:
        if LOCK_FILE.exists():
            # Check if lock is stale (>10 minutes old)
            lock_age = time.time() - LOCK_FILE.stat().st_mtime
            if lock_age > 600:
                LOCK_FILE.unlink()
            else:
                return False
        LOCK_FILE.write_text(str(time.time()))
        return True
    except Exception:
        return True  # proceed if lock fails


def release_lock() -> None:
    """Release refresh lock."""
    with contextlib.suppress(Exception):
        LOCK_FILE.unlink(missing_ok=True)


def refresh_token() -> bool:
    """Run the auto-login script to refresh the token."""
    log.info("Triggering token refresh...")
    try:
        result = subprocess.run(
            [str(BROWSING_VENV), str(AUTO_LOGIN_SCRIPT), "--force"],
            capture_output=True,
            text=True,
            timeout=180,  # 3 minute timeout
            cwd=str(ROOT),
        )
        if result.returncode == 0:
            log.info("Token refresh SUCCESS")
            return True
        log.error("Token refresh FAILED (exit %d): %s", result.returncode, result.stderr[-300:])
        return False
    except subprocess.TimeoutExpired:
        log.exception("Token refresh TIMEOUT (180s)")
        return False
    except Exception as e:
        log.exception("Token refresh error: %s", e)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Upstox token watchdog")
    parser.add_argument(
        "--threshold",
        type=int,
        default=THRESHOLD_MINUTES,
        help=f"Refresh if less than N minutes remaining (default: {THRESHOLD_MINUTES})",
    )
    parser.add_argument("--force", action="store_true", help="Force refresh regardless of remaining time")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "upstox_watchdog.log"),
        ],
    )

    remaining = get_token_remaining_minutes()

    if remaining is None:
        log.warning("No token found — triggering refresh")
        if acquire_lock():
            try:
                return 0 if refresh_token() else 1
            finally:
                release_lock()
        return 1

    log.info("Token remaining: %.1f min (threshold: %d min)", remaining, args.threshold)

    if remaining > args.threshold and not args.force:
        log.info("Token still valid — no refresh needed")
        return 0

    # Token expiring soon or force refresh
    if not acquire_lock():
        log.info("Another refresh is in progress — skipping")
        return 0

    try:
        success = refresh_token()
        if success:
            new_remaining = get_token_remaining_minutes()
            if new_remaining:
                log.info("After refresh: %.1f min remaining", new_remaining)
        return 0 if success else 1
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
