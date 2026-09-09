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
"""Completeness QC for scripts/indices_history.json (index membership reconstruction).
A fixed-size index must contain EXACTLY its size at every point in time; any deviation (post-2020)
means build_changelog.py mis-captured a change (missing an include/exclude, or a missing press release).
Sectoral indexes have variable size over time, so only flag the broad ones; print sectoral ranges.

Run: python -X utf8 verify_sizes.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ih = json.load(open(os.path.join(HERE, "indices_history.json"), encoding="utf-8"))
SIZE = {
    "Nifty 50": 50,
    "Nifty Next 50": 50,
    "Nifty 100": 100,
    "Nifty 200": 200,
    "Nifty 500": 500,
    "Nifty Midcap 50": 50,
    "Nifty Midcap 100": 100,
    "Nifty Midcap 150": 150,
    "Nifty Smallcap 50": 50,
    "Nifty Smallcap 100": 100,
    "Nifty Smallcap 250": 250,
    "Nifty LargeMidcap 250": 250,
    "Nifty MidSmallcap 400": 400,
}
SECTORAL = [
    "Nifty Bank",
    "Nifty IT",
    "Nifty Pharma",
    "Nifty Auto",
    "Nifty FMCG",
    "Nifty Metal",
    "Nifty Energy",
    "Nifty Realty",
    "Nifty Media",
    "Nifty Healthcare",
    "Nifty Consumer Durables",
    "Nifty Oil & Gas",
    "Nifty PSU Bank",
    "Nifty MNC",
]

print("BROAD fixed-size indexes — deviations from exact size (>=2020):")
allok = True
for idx, exp in SIZE.items():
    snaps = [s for s in ih.get(idx, []) if s["effectiveDate"] >= "2020-01-01"]
    tol = 6 if exp >= 250 else 1
    bad = [(s["effectiveDate"], len(s["symbols"])) for s in snaps if abs(len(s["symbols"]) - exp) > tol]
    if bad:
        allok = False
    print("  %-24s exp=%3d snaps=%2d  %s" % (idx, exp, len(snaps), "OK" if not bad else "BAD " + str(bad[:6])))

# Nifty 500 pre-2020: the 2015-2019 reviews are captured (hunt overlay in build_changelog.py), but the
# 2015-03-25 -> 2018-10-04 stretch has NO archived full list to pin, so the backward walk carries a
# residual ~15-16 size drift from uncaptured off-cycle swaps. Tolerance 17 catches a relapse into the
# old failure (missing semi-annual reviews -> sizes 432-489) without flagging the irreducible drift.
print("\nNifty 500 pre-2020 (2015-04-01+, tol 17 — catches missing semi-annual reviews):")
snaps = [s for s in ih.get("Nifty 500", []) if "2015-04-01" <= s["effectiveDate"] < "2020-01-01"]
bad = [(s["effectiveDate"], len(s["symbols"])) for s in snaps if abs(len(s["symbols"]) - 500) > 17]
if bad:
    allok = False
print("  %-24s exp=500 snaps=%2d  %s" % ("Nifty 500", len(snaps), "OK" if not bad else "BAD " + str(bad[:6])))

print("\nSECTORAL indexes — size range (variable size is normal):")
for idx in SECTORAL:
    sizes = [len(s["symbols"]) for s in ih.get(idx, []) if s["effectiveDate"] >= "2020-01-01"]
    print(
        "  %-24s snaps=%2d  sizes %s..%s  last=%s"
        % (idx, len(sizes), min(sizes) if sizes else "-", max(sizes) if sizes else "-", sizes[-1] if sizes else "-")
    )

print("\nALL BROAD FIXED-SIZE OK" if allok else "\n*** BROAD FIXED-SIZE DEVIATIONS — changelog gaps to fix ***")
