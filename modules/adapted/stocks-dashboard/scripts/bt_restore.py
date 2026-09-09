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


# -*- coding: utf-8 -*-
"""Restore the shared (open) backtest history from a daily backup, if it ever gets wiped/vandalised.
Pushes the chosen backup back into Supabase via the open write RPC.

  python scripts/bt_restore.py                       # restore from the NEWEST backup in backups/
  python scripts/bt_restore.py backups/bt_history_2026-06-19.json   # restore a specific day
  python scripts/bt_restore.py --list                # just list available backups
"""
import glob
import json
import os
import sys
import urllib.request

URL = "https://nebjnsndgrhumnkuipqy.supabase.co/rest/v1/rpc/bt_owner_set"
KEY = "sb_publishable_MDlQwiVc5deii91__UNeDg_z9r4Fk98"
SECRET = "sw_owner_8Kq2Lm9Xp4Rt7v"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAK = sorted(glob.glob(os.path.join(ROOT, "backups", "bt_history_*.json")))

if "--list" in sys.argv:
    for f in BAK:
        try:
            n = len(json.load(open(f)))
        except Exception:
            n = "?"
        print(f"  {os.path.basename(f)}  ({n} entries)")
    print("%d backups available" % len(BAK))
    sys.exit(0)

arg = [a for a in sys.argv[1:] if not a.startswith("-")]
path = arg[0] if arg else (BAK[-1] if BAK else None)
if not path or not os.path.exists(path):
    sys.exit("No backup file found. Run with --list to see options.")

data = json.load(open(path))
if not isinstance(data, list) or not data:
    sys.exit(f"Backup is empty/invalid: {path}")
body = json.dumps({"secret": SECRET, "payload": data}).encode()
req = urllib.request.Request(
    URL, body, {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
)
resp = urllib.request.urlopen(req, timeout=30).read().decode()
print("Restored %d entries from %s  (server: %s)" % (len(data), os.path.basename(path), resp or "ok"))
