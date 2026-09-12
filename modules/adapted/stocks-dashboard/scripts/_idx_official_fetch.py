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
"""Fetch EVERY official archived NSE/niftyindices sub-index constituent CSV.

These are the ONLY ground-truth point-in-time memberships for the 8 broad tiers.
CDX-enumerate all 200-status captures for each tier's niftyindices slug AND its
CNX-era predecessor, fetch+parse each, plus grab the live current list.

Writes _idx_official_snaps.json = {tier: {YYYYMMDD: [symbols]}} (symbols direct,
authoritative, no name resolution needed).
"""
import csv
import io
import json
import time
import urllib.request

from curl_cffi import requests as cr

UA = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}

# tier -> list of (host_path) to try; niftyindices current + CNX predecessor + nse archives
TIERS = {
    "Nifty 100": ["niftyindices.com/IndexConstituent/ind_nifty100list.csv"],
    "Nifty Midcap 100": [
        "niftyindices.com/IndexConstituent/ind_niftymidcap100list.csv",
        "nseindia.com/content/indices/ind_cnxmidcaplist.csv",
    ],
    "Nifty Midcap 50": [
        "niftyindices.com/IndexConstituent/ind_niftymidcap50list.csv",
        "nseindia.com/content/indices/ind_cnxmidcap50list.csv",
    ],
    "Nifty Smallcap 100": [
        "niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
        "nseindia.com/content/indices/ind_cnxsmallcaplist.csv",
    ],
    "Nifty Midcap 150": ["niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv"],
    "Nifty Smallcap 250": ["niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv"],
    "Nifty Smallcap 50": ["niftyindices.com/IndexConstituent/ind_niftysmallcap50list.csv"],
    "Nifty LargeMidcap 250": ["niftyindices.com/IndexConstituent/ind_niftylargemidcap250list.csv"],
    "Nifty MidSmallcap 400": ["niftyindices.com/IndexConstituent/ind_niftymidsmallcap400list.csv"],
}
# live current filenames (niftyindices serves these)
LIVE = {
    t: "https://www.niftyindices.com/IndexConstituent/ind_{}list.csv".format(
        t.lower().replace("nifty ", "nifty").replace(" ", "")
    )
    for t in TIERS
}


def cdx(path):
    q = f"https://web.archive.org/cdx/search/cdx?url={path}&output=json&filter=statuscode:200&collapse=digest"
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=60))[1:]
        except Exception:
            time.sleep(4)
    return []


def parse_csv(txt):
    syms = []
    for row in csv.reader(io.StringIO(txt)):
        if (
            len(row) >= 3
            and row[2].strip()
            and row[2].strip() not in ("Symbol", "Series")
            and row[0].strip() not in ("", "Company Name")
        ):
            syms.append(row[2].strip())
    return syms


snaps = {}
for tier, paths in TIERS.items():
    snaps[tier] = {}
    for path in paths:
        for ts, orig in [(r[1], r[2]) for r in cdx(path)]:
            d = ts[:8]
            if d in snaps[tier]:
                continue
            try:
                raw = (
                    urllib.request.urlopen(
                        urllib.request.Request(f"https://web.archive.org/web/{ts}id_/{orig}", headers=UA), timeout=45
                    )
                    .read()
                    .decode("utf-8", "replace")
                )
            except Exception:
                continue
            s = parse_csv(raw)
            if len(s) >= 30:
                snaps[tier][d] = s
    # live current
    try:
        raw = cr.get(LIVE[tier], impersonate="chrome", timeout=30, headers={"Accept-Encoding": "identity"}).text
        s = parse_csv(raw)
        if len(s) >= 30:
            snaps[tier]["LIVE"] = s
    except Exception:
        pass
    dates = sorted(snaps[tier])
    print(
        "%-24s %2d snapshots: %s"
        % (tier, len(snaps[tier]), ", ".join("%s(%d)" % (d, len(snaps[tier][d])) for d in dates)),
        flush=True,
    )

json.dump(snaps, open("_idx_official_snaps.json", "w"))
print("\nwrote _idx_official_snaps.json")
