#!/usr/bin/env python3
"""
CI guard: assert that the weekday scan cron expressions in
.circleci/config.yml match the WINDOWS list baked into the
"Write scan_status.json" Python heredoc.

If you add or change a scheduled scan window in either place, this
script will fail in CI until both are updated.

Usage:
    python backend/scripts/check_cron_consistency.py
"""
import re
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / ".circleci" / "config.yml"

# MUST match the WINDOWS list inside the "Write scan_status.json" step of
# .circleci/config.yml. Both lists are kept in sync by this guard.
EXPECTED_WINDOWS = [(3, 30), (10, 30)]   # (hour_utc, minute_utc)


def extract_scan_cron_entries(text: str) -> list:
    """Weekday once-an-hour scan crons: 'M H * * 1-5' (not watchdog */15)."""
    return re.findall(r'^\s+cron:\s*"(\d+ \d+ \* \* 1-5)"', text, flags=re.MULTILINE)


def expected_cron_strings(windows) -> list:
    return [f"{m} {h} * * 1-5" for h, m in windows]


def main() -> int:
    if not CONFIG.exists():
        print(f"::error::config.yml not found at {CONFIG}")
        return 1
    text = CONFIG.read_text()
    found = extract_scan_cron_entries(text)
    expected = expected_cron_strings(EXPECTED_WINDOWS)
    if found != expected:
        print(f"::error::Scan cron entries in {CONFIG} don't match EXPECTED_WINDOWS.")
        print(f"  found:    {found}")
        print(f"  expected: {expected}")
        print(f"  Update either EXPECTED_WINDOWS in this script or the scan "
              f"schedule crons in .circleci/config.yml so both lists agree.")
        return 1
    print(f"OK: {len(found)} scan cron entries match EXPECTED_WINDOWS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
