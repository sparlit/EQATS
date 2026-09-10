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


"""
Data Collection Launcher — starts all 3 collectors in parallel.

  1. premarket_collector  — 8:45 AM (global cues) + 10:00 AM (Asian)
  2. oi_collector         — every 15 min 9:20-15:29 (OI + chain) + 15:42 (CAS close + divergence)
  3. eod_collector        — 16:00 (candles, sectors, FII/DII, VIX, basis, breadth)

Usage:
    python start_collectors.py
"""

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    collectors = [
        ("premarket_collector", [sys.executable, "-m", "collectors.premarket_collector", "--schedule"]),
        ("oi_collector", [sys.executable, "-m", "collectors.oi_collector", "--schedule"]),
        ("eod_collector", [sys.executable, "-m", "collectors.eod_collector", "--schedule"]),
    ]

    procs = []
    for name, cmd in collectors:
        print(f"[LAUNCH] {name}: {' '.join(cmd)}")
        p = subprocess.Popen(cmd, cwd=BASE, env=env)
        procs.append((name, p))

    print(f"\n[OK] All {len(procs)} collectors running. Ctrl+C to stop.\n")

    try:
        for name, p in procs:
            p.wait()
            print(f"[DONE] {name} (exit {p.returncode})")
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down...")
        for name, p in procs:
            p.terminate()
        for name, p in procs:
            p.wait()
        print("[STOPPED]")


if __name__ == "__main__":
    main()
