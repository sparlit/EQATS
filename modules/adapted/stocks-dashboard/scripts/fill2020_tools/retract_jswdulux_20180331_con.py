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
"""RETRACT the JSWDULUX 2018-03 consolidated family — they are FY18 ANNUAL figures in a QUARTERLY slot.

WHAT WAS STORED (revop row [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC]):
    20180331  [700.41, 2719.35, 69.9, 298.69, 237.86, 400.14, 0, 54.9, 240.47]
The std family is a genuine quarter. The con family is the whole YEAR: revC 2719.35 against ~700/quarter,
opC 298.69 against 69.9, ebitC 240.47 against 54.9, patC 400.14 against a 237.86 quarter.

★ THE CAUSE IS FILER-SIDE MIS-TAGGING, INGESTED FAITHFULLY (§ FY-identity-can-be-filer-side).
Measured 2026-08-17 from the company's own two XBRL files for the SAME submission (filed 12-Jun-2018,
INDAS_35021_9038_11052018113258_WEB*.xml):

    CONSOLIDATED (_WEB_2)   OneD 2018-01-01..2018-03-31  RevenueFromOperations = 2719.35
                            FourD 2017-04-01..2018-03-31 RevenueFromOperations = 2719.35   <- IDENTICAL
                            OneD/FourD ProfitLossForPeriod = 400.14 on BOTH contexts too
    STANDALONE   (_WEB)     OneD (quarter) = 700.41   FourD (year) = 2719.35                <- correct
                            OneD PAT = 237.86         FourD PAT = 400.57

The filer stamped the ANNUAL figure onto the quarter context in the consolidated file only; the
standalone file distinguishes them properly. Reading OneD — normally the right thing, and what the
rest of this codebase does — therefore yielded the annual. NSE's own results-data row repeats it
(re_net_sale 271935 lakh, re_net_profit 40014, labelled "Non-Cumulative"), so the error is upstream of
us in two independent feeds.

★ AND THE FILING ITSELF SAYS NO QUARTER EXISTS. The attachment (AKZOINDIA_NA_12062018201445_1.zip ->
Financialresult31Mar2018.pdf, which HAS a text layer — no vision needed) titles p10:
    "Consolidated statement of financial results for TWELVE MONTHS ended 31 March 2018 and 31 March 2017"
Its only two columns are the years ended 31-Mar-2018 and 31-Mar-2017. There is no Q4 column anywhere in
the consolidated statement, and NSE lists no consolidated filing for any other FY18 quarter (its
Consolidated rows jump 31-Mar-2017 -> 31-Mar-2018 -> 30-Jun-2019). Consolidated quarterly reporting
only became compulsory from FY2020 (§51a).

WHY RETRACT RATHER THAN CORRECT. There is no Q4FY18 consolidated figure to correct TO:
  * no consolidated Q4 column is printed anywhere;
  * it cannot be derived — con revenue is absent for Jun/Sep/Dec 2017, so annual-minus-9M has no 9M;
  * and it must NOT be assumed equal to the standalone 700.41. That equality holds across FY19/FY20 for
    this group, but inferring it here is precisely the reasoning the aggregator holds were wrong to use.
"Unknown" is the honest value; a plausible wrong number is worse.
(Bonus finding, journalled but NOT acted on: p10 prints revenue GROSS at 27,928.4 mn with "Excise Duty"
734.9 mn as an expense row, and 27,928.4 - 734.9 = 27,193.5 = exactly the XBRL's 2719.35 cr. So our
stored annual is the net-of-excise definition, consistent with §11.)

WHAT THIS TOUCHES, and why each (a retraction must leave the store INTERNALLY CONSISTENT, §85):
  1. docs/sf_revop.json + scripts/revop_fundamentals.json  -> null revC/opC/patC/ebitC (slots 1,3,5,8),
     std slots untouched — they are a real quarter, verified against the standalone XBRL's OneD.
  2. docs/sf_fundamentals.json + scripts/fundamentals.json -> null the con PAT slot and its ann date.
  3. scripts/rev_defects.json + scripts/pat_defects.json   -> journal the verdict. `correct_*` is null
     on purpose: verify_fills_live treats a null as "a deliberate null verdict is not a claim", so this
     records the proof without asserting a replacement value.
  4. scripts/vision_rev_fills.json -> the con block's rev/op set to null with a retraction note. That
     ledger is _apply_reads.py's PROVENANCE journal rather than its input, but the applier is FILL-ONLY
     (`if cell[ri] is None: cell[ri] = c["rev"]`), and fill-only is no protection for a slot a
     retraction deliberately emptied (§85). Its own skip path is `if c.get("rev") is None: continue`,
     so nulling rev is what makes the entry inert if it is ever replayed.

Run: python3 -X utf8 scripts/fill2020_tools/retract_jswdulux_20180331_con.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
SYM, QE = "JSWDULUX", "20180331"
CON_SLOTS = {1: "revC", 3: "opC", 5: "patC", 8: "ebitC"}
DEFECT = (
    "FY18 ANNUAL figures stored in the 2018-03 QUARTER slot. The consolidated XBRL of the "
    "12-Jun-2018 submission (INDAS_35021_9038_11052018113258_WEB_2.xml) tags the SAME value on "
    "its quarter context and its year context — OneD 2018-01-01..2018-03-31 and FourD "
    "2017-04-01..2018-03-31 both carry RevenueFromOperations 2719.35 and ProfitLossForPeriod "
    "400.14 — while the standalone twin (_WEB.xml) distinguishes them correctly (OneD 700.41 / "
    "237.86, FourD 2719.35 / 400.57). NSE's results-data row repeats the annual as "
    "'Non-Cumulative' too. The filing's own consolidated statement is titled 'for TWELVE MONTHS "
    "ended 31 March 2018 and 31 March 2017' and prints NO quarter column, and no consolidated "
    "filing exists for any other FY18 quarter, so no Q4FY18 consolidated figure exists to "
    "correct to and it is not derivable. Retracted to null rather than assumed equal to the "
    "standalone 700.41."
)
SOURCE = (
    "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_35021_9038_11052018113258_WEB_2.xml "
    "(consolidated) vs ..._WEB.xml (standalone); attachment "
    "AKZOINDIA_NA_12062018201445_1.zip -> Financialresult31Mar2018.pdf p10"
)


def main():
    apply = "--apply" in sys.argv
    paths = {
        "revop_d": os.path.join(ROOT, "docs", "sf_revop.json"),
        "revop_s": os.path.join(SCRIPTS, "revop_fundamentals.json"),
        "fund_d": os.path.join(ROOT, "docs", "sf_fundamentals.json"),
        "fund_s": os.path.join(SCRIPTS, "fundamentals.json"),
        "revdef": os.path.join(SCRIPTS, "rev_defects.json"),
        "patdef": os.path.join(SCRIPTS, "pat_defects.json"),
        "vision": os.path.join(SCRIPTS, "vision_rev_fills.json"),
    }
    st = {k: json.load(open(p, encoding="utf-8")) for k, p in paths.items()}

    for key in ("revop_d", "revop_s"):
        row = (st[key].get(SYM) or {}).get(QE)
        if row is None:
            print(f"  !! {key} missing {SYM} {QE}")
            return 1
        print("  %-9s before: %s" % (key, row))
        for i in CON_SLOTS:
            if len(row) > i and row[i] is not None and apply:
                row[i] = None
        if apply:
            print("  %-9s after : %s" % (key, row))

    for key in ("fund_d", "fund_s"):
        rows = st[key].get(SYM) or []
        r = next((x for x in rows if x and x[0] == int(QE)), None)
        if r is None:
            print(f"  !! {key} missing {SYM} row {QE}")
            return 1
        print("  %-9s before: %s" % (key, r))
        if apply:
            r[3] = None
            if len(r) > 4:
                r[4] = None
            print("  %-9s after : %s" % (key, r))

    if apply:
        st["revdef"].setdefault(SYM, {})[QE] = {
            "bad_rev": 2719.35,
            "basis": "con",
            "correct_rev": None,
            "defect": DEFECT,
            "source": SOURCE,
            "also_retracted": {"opC": 298.69, "ebitC": 240.47},
        }
        st["patdef"].setdefault(SYM, {})[QE] = {
            "stored_pat_con": 400.14,
            "correct_pat_con": None,
            "defect": DEFECT,
            "source": SOURCE,
        }
        v = st["vision"].get(f"{SYM}|{QE}")
        if isinstance(v, dict) and isinstance(v.get("con"), dict):
            v["con"]["rev"] = None
            v["con"]["op"] = None
            v["con"]["retracted"] = DEFECT
        json.dump(st["revop_d"], open(paths["revop_d"], "w"), separators=(",", ":"))
        json.dump(st["revop_s"], open(paths["revop_s"], "w"), separators=(",", ":"))
        json.dump(st["fund_d"], open(paths["fund_d"], "w"), separators=(",", ":"))
        json.dump(st["fund_s"], open(paths["fund_s"], "w"), separators=(",", ":"))
        json.dump(st["revdef"], open(paths["revdef"], "w"), indent=1, sort_keys=True)
        json.dump(st["patdef"], open(paths["patdef"], "w"), indent=1, sort_keys=True)
        json.dump(st["vision"], open(paths["vision"], "w"), indent=1, sort_keys=True)
        print("\nWROTE 7 files (4 payload/mirror, 2 defect journals, 1 provenance ledger neutralised)")
    else:
        print("\nDRY RUN — re-run with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
