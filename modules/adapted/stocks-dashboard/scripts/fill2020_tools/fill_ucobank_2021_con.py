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
"""UCOBANK: fill 4 con PAT quarters (Mar/Jun/Sep/Dec-2021) from primary comparator data.

User approval 2026-08-19 ("yes", after being shown proof for all four). These four
quarters were correctly retracted 2026-08-18 as FABRICATED_PREFLOOR - the OLD value
was an exact std-copy (e.g. Mar-2021 fabricated conPAT = 80.03 = std). Gate-1 v2
confirms no DEDICATED Consolidated Financial Result was ever filed for any of these
four quarters, so that retraction stands correct.

But real, audited, DIFFERENT-FROM-STD consolidated figures for all four exist as
comparators inside LATER filings' segment-reporting notes / consolidated tables -
UCO Bank has one equity-accounted associate, Paschim Banga Gramin Bank, and every
subsequent quarterly consolidated filing prints "Net Profit (bank) + Share in
Profit of Associate = Consolidated Net Profit" for its current quarter AND its
immediately-preceding-quarter and year-ago comparators. Found by re-reading
MoneyControl in the user's own browser after they flagged this session's first
pass as incomplete - my initial DOM read of MC's table only captured columns
rendered by query time, missing the paginated remainder.

Every figure below is read from the primary BSE filing (not MoneyControl, which
was only the pointer) and anchored: each filing's own "Net Profit (bank)" column
for the comparator quarter reproduces our stored STANDALONE value for that same
quarter to within a paisa of lakh-rounding, proving column identity before the
associate-adjusted figure is trusted.

  Mar-2021: Net Profit 80.03 (== stored std 80.03 exact) + Associate -10.64 =
    Consolidated 69.39. Source: Mar-2022 filing (BSE 13-May-2022, "Audited
    Financial Results For The Quarter/Year Ended 31.03.2022"), Consolidated
    Segment Reporting note, year-ago column.
  Jun-2021: Net Profit 101.81 (~= stored std 101.79) + Associate -14.14 =
    Consolidated 87.67. Source: Jun-2022 filing (BSE 05-Aug-2022, "Reviewed
    Financial Results For The Quarter Ended 30.06.2022"), Consolidated Segment
    Reporting note, year-ago column.
  Sep-2021: Net Profit 205.39 (~= stored std 205.40) + Associate -4.10 =
    Consolidated 201.29. Source: Sep-2022 filing (BSE 03-Nov-2022, "Reviewed
    Financial Results For The Quarter/Half Year Ended 30.09.2022"), MAIN
    Consolidated Results table itself (not just the segment note), year-ago
    column.
  Dec-2021: Net Profit 310.39 (== stored std 310.39 exact) + Associate -17.66 =
    Consolidated 292.73. Source: Mar-2022 filing, Consolidated Segment
    Reporting note, immediately-preceding-quarter column.

Comparative-column convention (used throughout this campaign): annCon carries
the CARRYING filing's own date, never the quarter's own default stamp - so
Mar-2021 and Dec-2021 both take the Mar-2022 filing's date (they are two
different comparator columns in the SAME filing), Jun-2021 takes the Jun-2022
filing's date, Sep-2021 takes the Sep-2022 filing's date.

Revenue (rev_con) is deliberately NOT filled here: UCO Bank's associate is
equity-accounted (only its PAT share is added at the bottom line), so
Interest Earned / Total Income is never restated for the associate - rev_con
equals rev_std by the accounting method itself, confirmed in the Sep-2022
filing (its Sep-2021 Interest Earned comparator column reads 371979 lakh =
3719.79 cr, exactly the stored std revenue). Nothing to write there; the
existing None is the accurate absence of a SEPARATE consolidated revenue line,
not a gap.
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
SCR = WT + "scripts/"
WHEN = '2026-08-19 (user: "yes", after per-quarter proof shown for all four)'

F = [
    (
        20210331,
        69.39,
        20220513,
        (
            'BSE, "Audited Financial Results For The Quarter/Year Ended 31.03.2022" (filed 13-May-2022), '
            "Consolidated Segment Reporting note, year-ago column: Net Profit 8003 + Share in Profit of Associate "
            "(1064) = Consolidated Net Profit 6939 (Rs in Lakh)"
        ),
        "Net Profit column 80.03 == stored std 20210331 EXACT",
    ),
    (
        20210630,
        87.67,
        20220805,
        (
            'BSE, "Reviewed Financial Results For The Quarter Ended 30.06.2022" (filed 05-Aug-2022), Consolidated '
            "Segment Reporting note, year-ago column: Net Profit 10181 + Share in Profit of Associate (1414) = "
            "Consolidated Net Profit 8767 (Rs in Lakh)"
        ),
        "Net Profit column 101.81 ~= stored std 20210630 101.79 (lakh-rounding, 0.02 residual)",
    ),
    (
        20210930,
        201.29,
        20221103,
        (
            'BSE, "Reviewed Financial Results For The Quarter/Half Year Ended 30.09.2022" (filed 03-Nov-2022), '
            "MAIN Consolidated Results table, year-ago column: Net Profit 20539 + Share in Profit of Associate (410) "
            "= Consolidated Net Profit 20129 (Rs in Lakh)"
        ),
        "Net Profit column 205.39 ~= stored std 20210930 205.40 (1 paisa, lakh-rounding)",
    ),
    (
        20211231,
        292.73,
        20220513,
        (
            'BSE, "Audited Financial Results For The Quarter/Year Ended 31.03.2022" (filed 13-May-2022), same filing '
            "as 20210331 above, Consolidated Segment Reporting note, immediately-preceding-quarter column: Net Profit "
            "31039 + Share in Profit of Associate (1766) = Consolidated Net Profit 29273 (Rs in Lakh)"
        ),
        "Net Profit column 310.39 == stored std 20211231 EXACT",
    ),
]


def load(p):
    return json.load(open(p))


def dump(p, o):
    json.dump(o, open(p, "w"), separators=(",", ":"))


for path in (WT + "docs/sf_fundamentals.json", SCR + "fundamentals.json"):
    o = load(path)
    rows = o["UCOBANK"]
    for qe, con, ann, _src, _anc in F:
        r = next(x for x in rows if x[0] == qe)
        assert r[3] is None and r[4] is None, f"UCOBANK {qe} con already holds {r[3]!r}/{r[4]!r}"
        r[3] = con
        r[4] = ann
    dump(path, o)

p = SCR + "conpat_filing_fills.json"
led = load(p)
for qe, con, ann, src, anc in F:
    led["UCOBANK|%d|con" % qe] = {"con": con, "annCon": ann, "when": WHEN, "basis": "con", "src": src, "evidence": anc}
json.dump(led, open(p, "w"), indent=1)

p = SCR + "con_copy_retractions.json"
R = load(p)
for qe, con, ann, src, anc in F:
    k = "UCOBANK|%d" % qe
    R[k]["superseded_by_fill"] = (
        "2026-08-19: this cell was correctly emptied (the retracted value was an "
        "exact std-copy fabrication) but is NOT permanently unfillable - a real, "
        f"different-from-std consolidated figure ({con:.2f}) exists as a comparator in a "
        "LATER filing and has now been written via conpat_filing_fills. Do not "
        "treat this retraction entry as a reason to re-empty the cell."
    )
dump(p, R)

print("filled: %d quarters" % len(F))
for qe, con, ann, _s, _a in F:
    print("  %d con=%.2f ann=%d" % (qe, con, ann))
