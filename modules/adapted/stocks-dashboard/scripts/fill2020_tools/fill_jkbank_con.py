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
"""J&KBANK: fix Jun-2019 con, fill Mar-2019 con, fill Jun-2018 con.

User approval 2026-08-19 ("fill them", re: the 5 real-gap names). Source: BSE
532209, "Reviewed Financial Results Of The Bank For The Quarter Ended 30th
June, 2019 (Standalone & Consolidated)" (filed 03-Aug-2019), page 9 -
"CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER ENDED 30th JUNE, 2019", a
table entirely on the consolidated basis (no std/con column split to
disambiguate - unlike CANBK's combined table). Read directly via vision at
6x zoom after the OCR text layer proved too poor to trust (garbled: "TERMS
Percentage Number Percentage and bl o} Earning Profit Prqni").

Row 10 "Profit before tax" 116.60 | 221.61 | 94.30 | 658.69
Row 11 "Tax Expenses"        95.45 |   7.85 | 41.84 | 194.85
Row 12 "Net Profit after tax (10-11)": each column's arithmetic verified
independently: 116.60-95.45=21.15 (Jun-2019), 221.61-7.85=213.76 (Mar-2019),
94.30-41.84=52.46 (Jun-2018), 658.69-194.85=463.85... wait FY column not
needed here.

This surfaced a live discrepancy: our store held con=21.87 for Jun-2019,
EXACTLY equal to std (21.87=21.87) - the classic std-copy shape - while this
filing's own consolidated block gives 21.15, genuinely different from std.
No ledger entry traces the origin of the 21.87 figure (checked every ledger
keyed by symbol; none has a J&KBANK|20190630|con write), consistent with a
pre-campaign vendor artifact. Corrected here on the strength of THIS reading
alone: it is a labeled, standalone "CONSOLIDATED" table with the Jun-2019 and
Mar-2019 arithmetic (before-tax minus tax) closing exactly on every column,
which a copy-paste error would not do.

Revenue (Interest Earned, row 1) for Jun-2018: 1762.89 - matches the ALREADY
STORED rev_std for that quarter (1762.89) exactly on the con column too,
because this bank's consolidated scope is evidently associate-only (no
separate minority/associate line in this table at all - see the note above
row 12 skipping straight from tax to "Net Profit for the period", no
"Add: Share of Associates" or "Less: Minority Interest" rows), so con
revenue is identical to std revenue by the accounting method itself, same
as UCOBANK's finding.
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
SCR = WT + "scripts/"
WHEN = '2026-08-19 (user: "fill them")'
ANN = 20190803

SRC = (
    'BSE 532209, "Reviewed Financial Results Of The Bank For The Quarter Ended 30th June, 2019 '
    '(Standalone & Consolidated)" (filed 03-Aug-2019), page 9, "CONSOLIDATED FINANCIAL RESULTS FOR '
    'THE QUARTER ENDED 30th JUNE, 2019" - read via vision at 6x zoom, OCR text layer unreliable.'
)
ANCHOR = (
    "Row 12 = Row 10 (Profit before tax) - Row 11 (Tax), verified independently per column: "
    "116.60-95.45=21.15 (Jun-19), 221.61-7.85=213.76 (Mar-19), 94.30-41.84=52.46 (Jun-18)."
)

CHANGES = [
    (
        20190630,
        21.15,
        "CORRECTION: stored 21.87 exactly equalled std, a std-copy shape; this filing gives a genuinely different real figure",
    ),
    (20190331, 213.76, "FILL: was missing entirely"),
    (20180630, 52.46, "FILL: the original target, was missing entirely"),
]

for path in (WT + "docs/sf_fundamentals.json", SCR + "fundamentals.json"):
    o = json.load(open(path))
    rows = o["J&KBANK"]
    for qe, con, note in CHANGES:
        r = next(x for x in rows if x[0] == qe)
        r[3] = con
        r[4] = ANN
    json.dump(o, open(path, "w"), separators=(",", ":"))

REV_CON = 1762.89
for path in (WT + "docs/sf_revop.json", SCR + "revop_fundamentals.json"):
    o = json.load(open(path))
    d = o["J&KBANK"]
    c = d.get("20180630")
    if c is None:
        c = [None] * 9
        d["20180630"] = c
        o["J&KBANK"] = {k: d[k] for k in sorted(d)}
    c[1] = REV_CON
    if c[5] is None:
        c[5] = 52.46
    json.dump(o, open(path, "w"), separators=(",", ":"))

p = SCR + "conpat_filing_fills.json"
led = json.load(open(p))
for qe, con, note in CHANGES:
    led["J&KBANK|%d|con" % qe] = {
        "con": con,
        "annCon": ANN,
        "when": WHEN,
        "basis": "con",
        "src": SRC,
        "evidence": ANCHOR + " " + note,
    }
led["J&KBANK|20180630|con_rev"] = {
    "rev_con": REV_CON,
    "when": WHEN,
    "src": SRC,
    "evidence": "Row 1 Interest Earned Jun-2018 column = 1762.89, matches stored rev_std exactly (no minority/associate line in this table at all).",
}
json.dump(led, open(p, "w"), indent=1)

for qe, con, note in CHANGES:
    print("J&KBANK %d con=%.2f  (%s)" % (qe, con, note))
