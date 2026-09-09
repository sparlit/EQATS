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
"""FILL JSWDULUX 2018-06 consolidated PAT = 43.51, read straight off the printed statement.

WHY THIS CELL. 2e9ada5d0 ("Con-triad: 20 more names filled from the filings") filled JSWDULUX
2018-09 (36.75) and 2018-12 (60.38) from the comparative columns of the Q2/Q3 FY20 consolidated
filings, and its own proof for Sep-2018 used the H1 identity 43.51 + 36.75 = 80.26 == the printed
H1 Sep-2018 802.6 mn. But it never wrote the 43.51. So the store could not reproduce the identity
its own fill rested on: Sep and Dec had consolidated PAT while the June quarter in the SAME half
year sat empty. Nothing was red — mc_pat_fills.json holds this cell at 43.51, a held cell asserts
ABSENCE, and the slot was absent, so the guard was satisfied — which is exactly why it could sit
there unnoticed.

★ NOT DERIVED, READ. The subtraction was available (H1 802.6 - Q2 367.5 = 435.1) but a better source
exists and was used instead: the Q1FY20 consolidated filing prints the June-2018 quarter as its OWN
comparative column, so this is a printed figure, not an inference.

MEASURED 2026-08-17 by fetching the filing this session (not taken from the sibling's journal):
  * NSE quarterly-results index for JSWDULUX, Consolidated rows, jumps 31-Mar-2018 -> 30-Jun-2019 —
    so NO consolidated filing of its own exists for Jun-2018 and a comparative column is the only
    route. (Consolidated quarterly filing only became compulsory from FY2020, runbook §51a.)
  * Q1FY20 consolidated filing, NSE filingDate 09-Aug-2019 12:14, attachment
    AKZOINDIA_NA_09082019121424_1.zip -> ANILJunQuarterResults.pdf (the filename still carries the
    pre-rename symbol; JSWDULUX is the renamed AKZOINDIA, CIN L24292WB1954PLC021516).
  * p5 "Statement of Consolidated Unaudited Financial Results for the quarter ended 30 June 2019",
    declared "(Rs. in Million)", column "Quarter ended 30 June 2018 (Refer Note 1)", row 7 "Profit
    for the period from operations (5-6)" = 435.1 mn = Rs 43.51 crore.
  * ★ TWO ANCHORS ON THE SAME ROW, both reproducing stored cells exactly, which is what proves the
    right row and the right column were read: 30-Jun-2019 = 571.4 mn = 57.14 (stored con) and
    31-Mar-2019 = 703.4 mn = 70.34 (stored con). The 30-Jun-2019 figure is independently confirmed
    twice more, from that filing's XBRL (ProfitLossForPeriod on OneD 2019-04-01..2019-06-30 =
    571400000) and from NSE's results-data row (re_net_profit 5714 Rs lakh).
  * FY19 cross-check: printed year-ended-31-Mar-2019 = 2,110.0 mn; the four printed quarters
    435.1 + 367.5 + 603.8 + 703.4 = 2,109.8, i.e. 0.2 mn apart — the expected rounding, since each
    quarter is printed to 0.1 mn and Note 2 says the Q4 column is itself a balancing figure.
  * BASIS IS MOOT HERE, and the auditor says so rather than me: the Limited Review Report (p7-p8)
    lists the only consolidated entities as Akzo Nobel India Limited (Parent) and ICI India Research
    & Technology Centre (Subsidiary), and states the subsidiary's "total net profit/(loss) after tax
    of Rs. Nil". There is no non-controlling-interest block anywhere in the statement, so row 7 IS
    the owners figure. Note 1 also records that the Jun-2018 comparative was approved by the Board
    but NOT subjected to limited review — journalled because it is a real caveat on the number.

ANN DATE = 20190809, the date this figure first became public (the Q1FY20 filing), NOT the Jun-2018
quarter's own standalone announcement. A comparative is only knowable from the later filing, so
using the earlier date would be a look-ahead.

NOT DONE HERE, deliberately: the same printed column gives consolidated REVENUE 7,156.9 mn = 715.69
crore, which is exactly what mc_history_fills.json holds for this cell. Filling it would leave
JSWDULUX with consolidated revenue for Jun-2018 but not for Sep/Dec-2018 (the sibling filled neither),
and a one-quarter island is worse than a clean gap. The revenue triad should be done together.

Run: python3 -X utf8 scripts/fill2020_tools/fill_jswdulux_20180630_con.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

SYM, QE, CON, ANN = "JSWDULUX", 20180630, 43.51, 20190809
SRC = (
    "Akzo Nobel India (now JSWDULUX) Q1FY20 'Statement of Consolidated Unaudited Financial Results "
    "for the quarter ended 30 June 2019' (NSE filingDate 09-Aug-2019 12:14, attachment "
    "AKZOINDIA_NA_09082019121424_1.zip -> ANILJunQuarterResults.pdf) p5, column 'Quarter ended "
    "30 June 2018 (Refer Note 1)'"
)
EVIDENCE = (
    "printed comparative; row 7 'Profit for the period from operations (5-6)' 435.1 -> 43.51 "
    "crore (statement declares '(Rs. in Million)', 1 crore = 10 million). No NCI block, and the "
    "Limited Review Report states the sole subsidiary's net profit after tax is Rs. Nil -> row 7 "
    "IS the owners figure. Scanned page, read by rendering it at 230 dpi. No consolidated filing "
    "of its own exists for Jun-2018 (NSE con list jumps 20180331 -> 20190630)."
)
ANCHOR = (
    "SAME ROW, two stored cells reproduced EXACTLY: 30-Jun-2019 571.4 mn = 57.14 == stored con, "
    "31-Mar-2019 703.4 mn = 70.34 == stored con. The Jun-2019 figure is confirmed twice more "
    "independently: that filing's XBRL ProfitLossForPeriod on OneD 2019-04-01..2019-06-30 = "
    "571400000, and NSE results-data seq 1066336 re_net_profit = 5714 Rs lakh."
)
IDENTITY = (
    "Printed FY19 2,110.0 mn vs the four printed quarters 435.1 + 367.5 + 603.8 + 703.4 = "
    "2,109.8 — 0.2 mn apart, the expected rounding at 0.1 mn per quarter with a balancing Q4 "
    "(Note 2). Also closes the identity the SIBLING fill rested on but never wrote: 43.51 + "
    "36.75 = 80.26 == the printed H1 Sep-2018 802.6 mn, EXACT."
)
CAVEAT = (
    "Note 1 of the statement: the figures for the quarter ended 30 June 2018 were approved by the "
    "Board but have NOT been subjected to limited review/audit by the statutory auditors."
)


def load(p):
    return json.load(open(p, encoding="utf-8"))


def main():
    apply = "--apply" in sys.argv
    fund_s = os.path.join(SCRIPTS, "fundamentals.json")
    fund_d = os.path.join(ROOT, "docs", "sf_fundamentals.json")
    prov_p = os.path.join(SCRIPTS, "conpat_filing_fills.json")
    pin_p = os.path.join(SCRIPTS, "owners_basis_heals.json")

    fs, fd = load(fund_s), load(fund_d)
    prov, pin = load(prov_p), load(pin_p)

    changed = []
    for label, store, path in (("scripts/fundamentals.json", fs, fund_s), ("docs/sf_fundamentals.json", fd, fund_d)):
        rows = store.get(SYM)
        if not rows:
            print(f"  !! {label} has no {SYM}")
            return 1
        row = next((r for r in rows if r and r[0] == QE), None)
        if row is None:
            print(f"  !! {label} has no {SYM} row for {QE}")
            return 1
        print("  %-28s before: %s" % (label, row))
        if row[3] is not None and abs(row[3] - CON) > 0.011:
            print(f"     !! con slot already holds {row[3]}, NOT {CON} — stopping, this needs a human")
            return 1
        if row[3] is None:
            if apply:
                row[3], row[4] = CON, ANN
            changed.append((label, path, store))
        print("  %-28s after : [%s, %s, %s, %s, %s]" % (label, row[0], row[1], row[2], CON, ANN))

    if "JSWDULUX|20180630|con" not in prov:
        prov["JSWDULUX|20180630|con"] = {
            "con": CON,
            "annCon": ANN,
            "basis": "con",
            "when": "2026-08-17 23:0x IST",
            "src": SRC,
            "evidence": EVIDENCE,
            "anchor": ANCHOR,
            "identity": IDENTITY,
            "caveat": CAVEAT,
            "campaign": "con-yoy-triad",
            "fill_pass": "2026-08-17 jswdulux-h1-closeout",
            "prior_per_file": {"docs/sf_fundamentals.json": None, "scripts/fundamentals.json": None},
        }
        print(
            "  scripts/conpat_filing_fills.json   + JSWDULUX|20180630|con (provenance, registered in verify_fills_live)"
        )
    pk = "JSWDULUX|20180630|patC"
    if pk not in pin["cells"]:
        pin["cells"][pk] = {
            "owners": CON,
            "stored_before": None,
            "note": EVIDENCE,
            "source": SRC,
            "identity": IDENTITY,
            "anchor": ANCHOR,
            "caveat": CAVEAT,
        }
        print(
            f"  scripts/owners_basis_heals.json    + {pk} (THE PIN — without this the nightly applier reverts the fill)"
        )

    if not apply:
        print("\nDRY RUN — re-run with --apply to write")
        return 0
    json.dump(fs, open(fund_s, "w"), separators=(",", ":"))
    json.dump(fd, open(fund_d, "w"), separators=(",", ":"))
    json.dump(prov, open(prov_p, "w"), indent=1, sort_keys=True)
    json.dump(pin, open(pin_p, "w"), indent=1, sort_keys=True)
    print("\nWROTE 4 files. Now run: python3 -X utf8 scripts/settle_stale_holds.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
