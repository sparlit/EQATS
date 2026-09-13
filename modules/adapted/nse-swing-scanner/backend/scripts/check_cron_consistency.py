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
"""
CI guard: assert that the weekday scan cron expressions in
.github/workflows/scan.yml (the live schedule) match the SCAN_WINDOWS_UTC
list in backend/settings.py — the single source of truth consumed by
scan_status.json's window attribution and watchdog_check.py's staleness
logic. Also sanity-checks the watchdog's 15-min cron window.

History: this guard previously validated .circleci/config.yml's `triggers:`
block. Those triggers are inert on GitHub App projects (documented in the
CircleCI config, removed in 1.3.3), so the guard was checking a schedule
that never ran. It now checks the schedule that actually fires scans.

If you add or change a scheduled scan window, update BOTH
.github/workflows/scan.yml's `on.schedule` AND SCAN_WINDOWS_UTC in
backend/settings.py in the same commit — this script fails CI until they
agree.

Usage:
    python backend/scripts/check_cron_consistency.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_YML = REPO_ROOT / ".github" / "workflows" / "scan.yml"
WATCHDOG_YML = REPO_ROOT / ".github" / "workflows" / "watchdog.yml"

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from settings import SCAN_WINDOWS_UTC  # noqa: E402


def extract_scan_cron_entries(text: str) -> list:
    """Weekday once-an-hour scan crons: 'M H * * 1-5' (not watchdog */15)."""
    return re.findall(r'^\s+- cron:\s*"(\d+ \d+ \* \* 1-5)"', text, flags=re.MULTILINE)


def expected_cron_strings(windows) -> list:
    return [f"{m} {h} * * 1-5" for h, m in windows]


def main() -> int:
    failures = []

    # --- scan.yml crons vs SCAN_WINDOWS_UTC (the load-bearing check) ---
    if not SCAN_YML.exists():
        print(f"::error::scan.yml not found at {SCAN_YML}")
        return 1
    text = SCAN_YML.read_text()
    found = extract_scan_cron_entries(text)
    expected = expected_cron_strings(SCAN_WINDOWS_UTC)
    if found != expected:
        failures.append(
            f"Scan cron entries in {SCAN_YML.relative_to(REPO_ROOT)} don't match "
            f"SCAN_WINDOWS_UTC in backend/settings.py.\n"
            f"  found:    {found}\n"
            f"  expected: {expected}\n"
            f"  Update both in the same commit."
        )

    # --- watchdog cron sanity: 15-min cadence, weekday hours 1-13 UTC ---
    if WATCHDOG_YML.exists():
        wtext = WATCHDOG_YML.read_text()
        watchdog_crons = re.findall(r'^\s+- cron:\s*"([^"]+)"', wtext, flags=re.MULTILINE)
        if "*/15 1-13 * * 1-5" not in watchdog_crons:
            failures.append(
                "watchdog.yml cron must be '*/15 1-13 * * 1-5' (15-min ticks, "
                "06:30-19:00 IST weekdays). Found: "
                f"{watchdog_crons or 'none'}. If you intentionally changed the "
                "watchdog window, update this guard in the same commit."
            )

    if failures:
        for f in failures:
            print("::error::" + f)
        return 1

    print(f"OK: {len(found)} scan cron entries match SCAN_WINDOWS_UTC; watchdog cron ok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
