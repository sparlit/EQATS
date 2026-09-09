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
"""Official NSE daily index OHLC for the four F&O indices, from the archives'
all-indices file: /content/indices/ind_close_all_DDMMYYYY.csv (measured live).

Only needed for the old bhavcopy era (<= 2024-07-05; UDiFF carries UndrlygPric).
Resumable: skips dates already in scripts/fo_spot_nse.json. 404 = holiday.

Usage: python3 fetch_fo_spot_nse.py 2016-01-01 2024-07-05
"""
import csv
import datetime as dt
import io
import json
import os
import random
import sys
import time
import urllib.request

NAMES = {
    "Nifty 50": "NIFTY",
    "Nifty Bank": "BANKNIFTY",
    "Nifty Financial Services": "FINNIFTY",
    "Nifty Midcap Select": "MIDCPNIFTY",
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
OUT = os.path.join(os.path.dirname(__file__), "fo_spot_nse.json")


def main():
    start = dt.date.fromisoformat(sys.argv[1])
    end = dt.date.fromisoformat(sys.argv[2])
    data = json.load(open(OUT)) if os.path.exists(OUT) else {"_holidays": []}
    hol = set(data["_holidays"])
    d = start
    new = 0
    while d <= end:
        iso = d.isoformat()
        if d.weekday() >= 5 or iso in hol or any(iso in data.get(s, {}) for s in ("NIFTY",)):
            d += dt.timedelta(days=1)
            continue
        url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                text = r.read().decode("utf-8", "replace")
            got = 0
            for row in csv.DictReader(io.StringIO(text)):
                sym = NAMES.get((row.get("Index Name") or "").strip())
                if not sym:
                    continue
                try:
                    ohlc = [
                        round(float(row[k]), 2)
                        for k in ("Open Index Value", "High Index Value", "Low Index Value", "Closing Index Value")
                    ]
                except (ValueError, KeyError):
                    continue
                data.setdefault(sym, {})[iso] = ohlc
                got += 1
            if not got:
                print(f"{iso}: 200 but 0 index rows!", file=sys.stderr)
            new += 1
            time.sleep(0.3 + random.random() * 0.25)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                hol.add(iso)
            time.sleep(0.4)
        except Exception:
            time.sleep(2)
        if new and new % 200 == 0:
            data["_holidays"] = sorted(hol)
            json.dump(data, open(OUT, "w"), separators=(",", ":"))
            print(f"...{iso} fetched={new}", flush=True)
        d += dt.timedelta(days=1)
    data["_holidays"] = sorted(hol)
    json.dump(data, open(OUT, "w"), separators=(",", ":"))
    for s in NAMES.values():
        m = data.get(s, {})
        print(s, len(m), min(m, default="-"), max(m, default="-"))


if __name__ == "__main__":
    main()
