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
"""HINDALCO 2018-09 / 2018-12 consolidated revenue — and the retraction of a WRONG value this
campaign itself wrote.  (2026-08-11, FILL-2018)

★ WHAT WENT WRONG, measured. The §58 sweep landed **HINDALCO 2018-12 revC = 332,131.0**. Its own
consolidated neighbours run 31,077 / 33,745 / 29,972 / 29,657 / 29,197, so the value is 10x its true
magnitude. It passed every guard the sweep has: the PAT column anchor was CORRECT (the right column
was picked), `con-rev-far-below-std` only fires BELOW standalone, and §54a rightly forbids banding
against the other basis (Hindalco's real con/std is 2.9x, but BBTC's is 44-61x, so that test would
reject real data).

★ THE CAUSE — a NEW corruption class. The source document (BSE attachment
0fee6aeb-7cdf-41b3-9b37-4324e37ea168, Hindalco's 12-Feb-2020 filing, used by `--rescue` for its
year-ago column) has a text layer that is corrupted IN THE DIGITS while remaining perfectly
parseable. Page 35, the audited statement, extracts as:

    Revenue from Operations | 29,197 | 29,657 | 33,2131 | 88,826 | 96,797 | 130,542
                                                 ^^^^^^^ printed 33,213 -- an extra digit is fused on

Strip the comma and `33,2131` becomes 332131. Same page: `Other Income | 297 | 287. | 2701`, and
`(26 | (29) | (25]`. This is NOT §51b (letters substituted, so keyword search fails loudly) and NOT
§75 (tokens rendered three times, so no label matches). It is worse than either, because **the
corrupted token is a VALID NUMBER**: no regex, no label check and no anchor can see anything wrong.
Only a magnitude test against the company's own same-basis history catches it
(`screen_neighbour_band.py`, §54a).

★ THE TRUE VALUES, from the same document, four independent prints plus prose:
  p2  "Consolidated Financial Highlights ... (Rs. Crore)":
          Particulars              Q3 FY19   Q2 FY20   Q3 FY20   9M FY19   9M FY20
          Revenue from Operations   33,213    29,657    29,197    96,797    88,826
  p3  prose: "Hindalco's Consolidated Revenue for Q3 FY20 stood at Rs. 29,197 crore compared to
          Rs. 33,213 crore in the same quarter last year."
  p28 / p32 segment tables: the same 33,213 / 29,657 / 29,197 / 96,797 / 88,826 row.

  Q3 FY19 IS the quarter ended 31-Dec-2018 -> revC = 33,213.

★ THREE INDEPENDENT CHECKS, all passing:
  1. the SAME ROW reproduces two values we already store, to the rupee: 29,657 == stored 2019-09-30
     revC and 29,197 == stored 2019-12-31 revC;
  2. FY19 minus 9M FY19 = 130,542 - 96,797 = 33,745 against our STORED 2019-03-31 revC of 33,745.62
     -- 0.002%. The printed annual, the printed 9-month and our stored quarter agree, which is what
     proves the printed table is the same entity, basis and scale as our series (§45);
  3. 33,213 sits inside Hindalco's own consolidated band (29,197 .. 33,745 across the surrounding
     five quarters) where 332,131 sat 10x outside it.

★ AND IT CLOSES A SECOND CELL. 2018-09 revC is also an open target and has no stored con PAT, so
§64 blocks every anchored reader from it. The printed 9-month total reaches it by arithmetic (§45):

    9M FY19 96,797 - Q1 (2018-06, stored 31,077.53) - Q3 (2018-12, 33,213) = 32,506.47

PRECISION. The printed figures are crore-rounded integers -- FY19 130,542 against a stored Q4 of
33,745.62 proves the source rounds. So both cells are written with `precision: crore-rounded`
(§60e's rule: a sourced approximation with honest provenance beats a hole, but it must be LABELLED
so a later pass refines it and nobody mistakes it for a filing-precision read). The derived
2018-09 cell carries the wider band, since it inherits the rounding of two printed totals.

  python -X utf8 scripts/fill2020_tools/apply_hindalco_2018.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills_2018.json")
DOC = "BSE ann 0fee6aeb-7cdf-41b3-9b37-4324e37ea168 (Hindalco, filed 12-Feb-2020)"

WRONG = 332131.0
CELLS = {
    "20181231": {
        "revC": 33213.0,
        "precision": "crore-rounded",
        "src": DOC + " p2 'Consolidated Financial Highlights ... (Rs. Crore)', column 'Q3 FY19'",
        "corroboration": [
            "p3 prose: 'compared to Rs. 33,213 crore in the same quarter last year'",
            "p28 + p32 segment tables print the identical row",
            "same row reproduces stored revC 29,657.00 (2019-09-30) and 29,197.00 (2019-12-31)",
            "FY19 130,542 - 9M FY19 96,797 = 33,745 vs stored 2019-03-31 revC 33,745.62 (0.002%)",
        ],
        "retracts": {
            "wrong_value": WRONG,
            "why": "text layer prints the token as '33,2131' - an extra digit fused onto 33,213 - "
            "which parses cleanly as 332131 and is 10x the true magnitude. Caught by the "
            "same-basis neighbour band (§54a), invisible to every other guard.",
        },
    },
    "20180930": {
        "revC": 32506.47,
        "precision": "crore-rounded (derived; inherits the rounding of two printed totals)",
        "src": DOC + " p2: 9M FY19 96,797 minus Q1 (stored 31,077.53) minus Q3 (33,213)",
        "corroboration": [
            "§45 9-month identity; §64 otherwise blocks this cell (no stored con PAT)",
            (
                "FY19 - 9M FY19 reproduces stored 2019-03-31 revC to 0.002%, proving the printed "
                "totals share our series' entity, basis and scale"
            ),
        ],
    },
}


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP_DOCS))
    cur = revop.get("HINDALCO", {})

    # Re-prove the anchors against CURRENT data before touching anything: the dataset moves under
    # us (CI + other sessions), and a heal that was right an hour ago may not be right now.
    checks = [
        ("2019-09-30 revC == 29,657.00", (cur.get("20190930") or [None] * 2)[1], 29657.0),
        ("2019-12-31 revC == 29,197.00", (cur.get("20191231") or [None] * 2)[1], 29197.0),
        ("2019-03-31 revC ~= 33,745", (cur.get("20190331") or [None] * 2)[1], 33745.62),
        ("2018-06-30 revC == 31,077.53", (cur.get("20180630") or [None] * 2)[1], 31077.53),
    ]
    ok = True
    for label, got, want in checks:
        good = got is not None and abs(got - want) <= max(0.01, 0.0005 * abs(want))
        print("  %-32s stored %-12s %s" % (label, got, "OK" if good else "★ MOVED — ABORT"))
        ok = ok and good
    if not ok:
        print("\nanchors have moved; refusing to write (§0: re-prove, never assume).")
        return

    now = (cur.get("20181231") or [None] * 2)[1]
    print(f"\n  current 2018-12-31 revC in the file: {now}")
    if now is not None and abs(now - WRONG) > 0.01:
        print("  ★ it is no longer the value this tool was written to retract — ABORT.")
        return

    if not apply_it:
        print("\nDRY RUN. Would write:")
        for q, c in CELLS.items():
            print("    {} revC = {}   ({})".format(q, c["revC"], c["precision"]))
        return

    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        rows = d.setdefault("HINDALCO", {})
        for q, c in CELLS.items():
            row = rows.get(q) or [None] * 6 + [0, None, None]
            while len(row) < 9:
                row.append(None)
            row[1] = c["revC"]  # deliberate overwrite ONLY for the retracted cell
            rows[q] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print(f"  wrote {os.path.basename(path)}")

    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    for q, c in CELLS.items():
        led[f"HINDALCO|{q}|revC"] = c
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print(f"  journalled -> {os.path.basename(LEDGER)}")


if __name__ == "__main__":
    main()
