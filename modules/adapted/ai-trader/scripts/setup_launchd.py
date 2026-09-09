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
Setup macOS LaunchAgent for automatic tick collection.

This creates a .plist file that tells macOS to run the tick collector
every weekday at 9:00 AM IST (before market opens at 9:15).

Usage:
  python scripts/setup_launchd.py install    # install and load
  python scripts/setup_launchd.py uninstall  # unload and remove
  python scripts/setup_launchd.py status     # check if running
"""

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.aitrader.tickcollector"
PROJECT_DIR = Path(__file__).resolve().parent.parent
PYTHON_PATH = PROJECT_DIR / ".venv" / "bin" / "python"
SCRIPT_PATH = PROJECT_DIR / "scripts" / "collect_ticks.py"
LOG_DIR = PROJECT_DIR / "logs"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{LABEL}.plist"

PLIST_CONTENT = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON_PATH}</string>
        <string>{SCRIPT_PATH}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{PROJECT_DIR}</string>

    <!-- Run at 9:00 AM IST every weekday (Mon=1 ... Fri=5) -->
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Weekday</key><integer>1</integer>
            <key>Hour</key><integer>9</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key><integer>2</integer>
            <key>Hour</key><integer>9</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key><integer>3</integer>
            <key>Hour</key><integer>9</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key><integer>4</integer>
            <key>Hour</key><integer>9</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key><integer>5</integer>
            <key>Hour</key><integer>9</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
    </array>

    <key>StandardOutPath</key>
    <string>{LOG_DIR}/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/launchd_stderr.log</string>

    <!-- Environment variables -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{PROJECT_DIR / ".venv" / "bin"}</string>
    </dict>

    <!-- Don't restart if it exits normally -->
    <key>KeepAlive</key>
    <false/>

    <!-- Allow it to run for up to 7 hours (market hours) -->
    <key>ExitTimeOut</key>
    <integer>25200</integer>
</dict>
</plist>
"""


def install():
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Verify paths
    if not PYTHON_PATH.exists():
        print(f"  ERROR: Python not found at {PYTHON_PATH}")
        print("  Make sure the virtual environment exists.")
        sys.exit(1)

    if not SCRIPT_PATH.exists():
        print(f"  ERROR: Script not found at {SCRIPT_PATH}")
        sys.exit(1)

    # Write plist
    PLIST_PATH.write_text(PLIST_CONTENT)
    print(f"  Created: {PLIST_PATH}")

    # Load the agent
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"  Loaded:  {LABEL}")
    print()
    print("  The tick collector will auto-start at 9:00 AM IST every weekday.")
    print(f"  Logs: {LOG_DIR}/tick_collector_*.log")
    print(f"  Launchd logs: {LOG_DIR}/launchd_stdout.log")


def uninstall():
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.unlink()
        print(f"  Unloaded and removed: {LABEL}")
    else:
        print(f"  Not installed: {PLIST_PATH} does not exist.")


def status():
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    found = False
    for line in result.stdout.splitlines():
        if LABEL in line:
            print(f"  {line}")
            found = True
    if not found:
        print(f"  {LABEL} is not loaded.")
    else:
        print(f"  Plist: {PLIST_PATH}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/setup_launchd.py [install|uninstall|status]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    print(f"  LaunchAgent: {LABEL}")

    if cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    elif cmd == "status":
        status()
    else:
        print(f"  Unknown command: {cmd}")
