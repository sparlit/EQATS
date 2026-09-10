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
"""CANBK: fill Jun-2018 con PAT + con revenue, from the same-table comparative
in the Jun-2019 filing.

User approval 2026-08-19 ("fill them", re: the 5 real-gap names the corrected
MC sweep found). Found via MC's "Net P/L After M.I & Associates" row reaching
back to Jun-2018 (340), a genuine reach beyond our own con series (which
starts Sep-2018) - then verified against the primary filing myself rather than
trusting MC's rounded figure.

Source: BSE 532483, "Board Meeting - Announcement Of Reviewed Financial
Results (Standalone & Consolidated) For The Quarter Ended 30th June 2019"
(filed 24-Jul-2019), page 2 - a single combined table, Standalone columns on
the left (x~338-523), Consolidated on the right (x~585-774), each block
[Quarter Ended current | Quarter Ended preceding | Quarter Ended year-ago |
Year Ended], geometrically extracted (word x,y positions, not the merged text
layer which interleaves the two blocks unreadably).

Row 17 "Net Profit(+)/Loss(-) after Minority Interest (14+15-16)" = Row 14
(raw consolidated profit) + Row 15 (Share of Earnings in Associates) - Row 16
(Minority Interest), computed independently for all four columns and the
arithmetic closes exactly on every one:
  Jun-2019: 373.88 + 25.81 - 16.65 = 383.04  == stored con 20190630 EXACT
  Mar-2019: -480.71 + 25.32 - 35.97 = -491.36 == stored con 20190331 EXACT
  Jun-2018: 313.58 + 42.07 - 14.97 = 340.68  <- the target
  FY19:     547.14 + 148.91 - 94.20 = 601.85

Two of four columns are exact matches to values already in our store from a
completely different filing (the Sep-2019/Dec-2019 comparative fills done
earlier this session) - about as strong a same-table double-anchor as this
campaign has had. Revenue (Interest Earned) row for the same Jun-2018 column:
std 11359.55 (matches our ALREADY-STORED std exactly - a third anchor), con
11688.39 (new).
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
SCR = WT + "scripts/"
WHEN = '2026-08-19 (user: "fill them")'
QE = 20180630
CON = 340.68
REV_CON = 11688.39
ANN = 20190724

SRC = (
    'BSE 532483, "Board Meeting - Announcement Of Reviewed Financial Results (Standalone & '
    'Consolidated) For The Quarter Ended 30th June 2019" (filed 24-Jul-2019), page 2, geometric '
    "column extraction. Row 17 (Net Profit after Minority Interest) = Row 14 (raw consolidated "
    "profit 313.58) + Row 15 (Share of Earnings in Associates 42.07) - Row 16 (Minority Interest "
    "14.97) = 340.68."
)
ANCHOR = (
    "Same table, same row, Jun-2019 and Mar-2019 columns both reproduce stored con EXACTLY "
    "(383.04 and -491.36); std Jun-2018 (281.49) and rev_std Jun-2018 (11359.55) both already "
    "stored and match this filing's own std block exactly - three independent anchors on one page."
)

for path in (WT + "docs/sf_fundamentals.json", SCR + "fundamentals.json"):
    o = json.load(open(path))
    r = next(x for x in o["CANBK"] if x[0] == QE)
    assert r[3] is None, f"CANBK {QE} con already holds {r[3]!r}"
    r[3] = CON
    r[4] = ANN
    json.dump(o, open(path, "w"), separators=(",", ":"))

for path in (WT + "docs/sf_revop.json", SCR + "revop_fundamentals.json"):
    o = json.load(open(path))
    c = o["CANBK"][str(QE)]
    assert c[1] is None, f"CANBK {QE} rev_con already holds {c[1]!r}"
    c[1] = REV_CON
    if c[5] is None:
        c[5] = CON
    json.dump(o, open(path, "w"), separators=(",", ":"))

p = SCR + "conpat_filing_fills.json"
led = json.load(open(p))
led["CANBK|%d|con" % QE] = {"con": CON, "annCon": ANN, "when": WHEN, "basis": "con", "src": SRC, "evidence": ANCHOR}
led["CANBK|%d|con_rev" % QE] = {"rev_con": REV_CON, "when": WHEN, "src": SRC, "evidence": ANCHOR}
json.dump(led, open(p, "w"), indent=1)

print("CANBK %d: con=%.2f rev_con=%.2f ann=%d" % (QE, CON, REV_CON, ANN))
