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
"""FILL the JSWDULUX FY19 consolidated-REVENUE triad (Jun/Sep/Dec 2018), read off printed comparatives.

COMPANION to fill_jswdulux_20180630_con.py, which filled the con PAT side. Those three quarters had
consolidated PAT but no consolidated revenue, and mc_history_fills.json held all three revenue cells
as suspected aggregator copies of standalone (715.69 / 713.8 / 783.28 — each identical to our stored
standalone, which is precisely what that screen cannot adjudicate). Done as a TRIAD on purpose: one
filled quarter inside an empty three is worse than a clean gap, because it makes a partial year look
like a complete one.

WHY A COMPARATIVE IS THE ONLY ROUTE. NSE's Consolidated rows for this symbol jump 31-Mar-2018 ->
30-Jun-2019: no consolidated filing of its own exists for any FY19 quarter (consolidated quarterly
filing only became compulsory from FY2020, runbook 51a). JSWDULUX is the renamed AKZOINDIA (CIN
L24292WB1954PLC021516) and the attachments still carry the old symbol.

MEASURED 2026-08-17 by fetching all three filings this session and rendering the scanned statement
pages (pages 2-8/2-11 of these PDFs have NO text layer). Each value is a printed figure in a column
headed with its own quarter, and each read carries TWO ANCHORS ON THE SAME ROW that reproduce cells
already stored, which is what proves the right row and the right column were read:

  Jun-2018  7,156.9 mn -> 715.69   Q1FY20 filing (filed 09-Aug-2019 12:14), p5
            anchors on row 1(a): 30-Jun-2019 7,196.9 -> 719.69 == stored revC,
                                 31-Mar-2019 7,055.8 -> 705.58 == stored revC
  Sep-2018  7,138.0 mn -> 713.80   Q2FY20 filing (filed 09-Nov-2019 15:51), p7
            anchors: 30-Sep-2019 6,338.2 -> 633.82 == stored revC,
                     30-Jun-2019 7,196.9 -> 719.69 == stored revC
  Dec-2018  7,832.8 mn -> 783.28   Q3FY20 filing (filed 07-Feb-2020 12:49), p7
            anchors: 31-Dec-2019 7,270.3 -> 727.03 == stored revC,
                     30-Sep-2019 6,338.2 -> 633.82 == stored revC

★ AND THE WHOLE FY19 REVENUE YEAR CLOSES EXACTLY, across three separate filings — no rounding slack
anywhere, which is a far stronger check than any single read:
    printed H1 Sep-2018   14,294.9 == 7,156.9 + 7,138.0
    printed 9M  Dec-2018  22,127.7 == 7,156.9 + 7,138.0 + 7,832.8
    printed FY19          29,183.5 == 22,127.7 + 7,055.8 (the printed Q4 column)
(The PAT side closes to 0.2 mn instead, because its Q4 column is a balancing figure per Note 2.)

★ CON == STD HERE IS EXPLAINED, NOT ASSUMED. All three equal our stored standalone to the paisa,
which is exactly the shape the holds were suspicious of. The filings answer it: the Limited Review
Reports list the only consolidated entities as Akzo Nobel India Limited (Parent) and ICI India
Research & Technology Centre (Subsidiary), and state that subsidiary's total revenues as Rs. 3
million against a group ~7,200 million, with net profit after tax Rs. Nil. There is no NCI block
anywhere in any of the three statements. So the equality is a fact about this group, and — decisively
— these numbers were READ FROM THE CONSOLIDATED DOCUMENT, not inferred from the standalone.

⚠️ CAVEAT, journalled rather than buried: each filing's Note 1 / review report records that the FY19
comparative figures were approved by the Board but NOT subjected to limited review or audit. Best and
only source, and unreviewed.

Run: python3 -X utf8 scripts/fill2020_tools/fill_jswdulux_conrev_triad.py [--apply]
Then: python3 -X utf8 scripts/settle_stale_holds.py --apply   (lifts the three now-stale holds)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
SYM = "JSWDULUX"
REVC = 1  # revop slot 1 = revC (slot 0 is revS)

CELLS = {
    "20180630": {
        "rev": 715.69,
        "mn": "7,156.9",
        "filing": "Q1FY20",
        "filed": "09-Aug-2019 12:14",
        "page": "p5",
        "zipname": "AKZOINDIA_NA_09082019121424_1.zip -> ANILJunQuarterResults.pdf",
        "col": "Quarter ended 30 June 2018 (Refer Note 1)",
        "anchors": "same row 1(a): 30-Jun-2019 7,196.9 -> 719.69 == stored revC; 31-Mar-2019 7,055.8 -> 705.58 == stored revC",
    },
    "20180930": {
        "rev": 713.80,
        "mn": "7,138.0",
        "filing": "Q2FY20",
        "filed": "09-Nov-2019 15:51",
        "page": "p7",
        "zipname": "AKZOINDIA_NA_09112019155154_1.zip -> AkzoIndiaQFRSep2019.pdf",
        "col": "Quarter ended 30 September 2018 (Refer Note 1)",
        "anchors": "same row 1(a): 30-Sep-2019 6,338.2 -> 633.82 == stored revC; 30-Jun-2019 7,196.9 -> 719.69 == stored revC",
    },
    "20181231": {
        "rev": 783.28,
        "mn": "7,832.8",
        "filing": "Q3FY20",
        "filed": "07-Feb-2020 12:49",
        "page": "p7",
        "zipname": "AKZOINDIA_NA_07022020124954_1.zip -> AkzoIndiaQFRDec19.pdf",
        "col": "Quarter ended 31 December 2018",
        "anchors": "same row 1(a): 31-Dec-2019 7,270.3 -> 727.03 == stored revC; 30-Sep-2019 6,338.2 -> 633.82 == stored revC",
    },
}
IDENTITY = (
    "FY19 revenue closes EXACTLY across three filings, no rounding slack: printed H1 Sep-2018 "
    "14,294.9 == 7,156.9 + 7,138.0; printed 9M Dec-2018 22,127.7 == 7,156.9 + 7,138.0 + "
    "7,832.8; printed FY19 29,183.5 == 22,127.7 + 7,055.8 (the printed Q4 column)."
)
CONVENTION = (
    "Equals our stored standalone to the paisa, and the filings explain why rather than "
    "leaving it unresolved: the only consolidated entities are the Parent and ICI India "
    "Research & Technology Centre, whose total revenues the review report puts at Rs. 3 "
    "million against a group ~7,200 million; no NCI block exists in any of the three "
    "statements. Read FROM the consolidated document, not inferred from the standalone."
)
CAVEAT = (
    "Note 1 / review report of each filing: the FY19 comparative figures were approved by the "
    "Board but NOT subjected to limited review or audit."
)


def main():
    apply = "--apply" in sys.argv
    rf_p = os.path.join(SCRIPTS, "revop_fundamentals.json")
    rd_p = os.path.join(ROOT, "docs", "sf_revop.json")
    pv_p = os.path.join(SCRIPTS, "conpat_filing_fills.json")
    rf, rd, pv = (json.load(open(p, encoding="utf-8")) for p in (rf_p, rd_p, pv_p))

    for qe, c in sorted(CELLS.items()):
        for label, store in (("scripts/revop_fundamentals.json", rf), ("docs/sf_revop.json", rd)):
            row = (store.get(SYM) or {}).get(qe)
            if row is None:
                print(f"  !! {label} has no {SYM} {qe}")
                return 1
            cur = row[REVC] if len(row) > REVC else None
            if cur is not None and abs(cur - c["rev"]) > 0.011:
                print(
                    "  !! {} {} revC already holds {}, not {} — stopping, needs a human".format(
                        label, qe, cur, c["rev"]
                    )
                )
                return 1
            print("  %-32s %s revC: %s -> %s" % (label, qe, cur, c["rev"]))
            if apply:
                row[REVC] = c["rev"]
        key = f"{SYM}|{qe}|con_rev"
        if key not in pv:
            pv[key] = {
                "rev_con": c["rev"],
                "basis": "con",
                "src": (
                    "Akzo Nobel India (now JSWDULUX) {} 'Statement of Consolidated Unaudited "
                    "Financial Results' (NSE filingDate {}, attachment {}) {}, column '{}'".format(
                        c["filing"], c["filed"], c["zipname"], c["page"], c["col"]
                    )
                ),
                "evidence": (
                    "printed comparative; row 1(a) 'Revenue from operations' {} Rs million = "
                    "{} crore (statement declares '(Rs. in Million)', 1 crore = 10 million). "
                    "Scanned page, no text layer — rendered at 230 dpi and read.".format(c["mn"], c["rev"])
                ),
                "anchor": c["anchors"],
                "identity": IDENTITY,
                "convention": CONVENTION,
                "caveat": CAVEAT,
                "why": (
                    "the con PAT triad was filled without its revenue twin, leaving three quarters "
                    "with consolidated PAT and no consolidated revenue"
                ),
                "campaign": "con-yoy-triad",
                "fill_pass": "2026-08-17 jswdulux-conrev-triad",
                "when": "2026-08-17 23:2x IST",
            }
            print(f"  scripts/conpat_filing_fills.json  + {key}")

    if not apply:
        print("\nDRY RUN — re-run with --apply to write")
        return 0
    json.dump(rf, open(rf_p, "w"), separators=(",", ":"))
    json.dump(rd, open(rd_p, "w"), separators=(",", ":"))
    json.dump(pv, open(pv_p, "w"), indent=1, sort_keys=True)
    print("\nWROTE 3 files. Now: python3 -X utf8 scripts/settle_stale_holds.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
