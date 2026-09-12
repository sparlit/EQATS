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
"""TIMKEN consolidated: correct two copied PAT cells and fill three revenue cells, from the filings.

The user found TIMKEN 2025-09-30 storing consolidated PAT 89.47 -- which is its STANDALONE figure
sitting in the con slot. They were right, and detect_con_copy.py then found it was three TIMKEN
quarters, not one, plus eleven other companies.

WHY THE COPY HAPPENED (worth recording, because it is a whole cohort not a one-off). TIMKEN filed
STANDALONE ONLY through Sep-2025 -- NSE's index lists 75 filings for it, every one Non-Consolidated.
It began consolidating with the Dec-2025 results, which is also the first filing to carry restated
consolidated COMPARATIVES for the earlier quarters. So at the time those quarters were ingested no
consolidated statement existed, the con slot took the standalone number, and the real consolidated
figures only became public later, inside a subsequent filing.

EVIDENCE, from TIMKEN's own consolidated statements (Rs million, /10 -> crore):

  Dec-2025 filing, p5 -- columns: Dec-2025 | Sep-2025 | Dec-2024
      Revenue from operations   7,796.69 | 7,863.54 | 6,833.51
      Net Profit after tax (3-4)  545.56 |   935.99
  Mar-2026 filing, p16 -- columns: Mar-2026 | Dec-2025 | Mar-2025
      Revenue from operations  10,898.26 | 7,796.69 | 9,514.57
      Net Profit after tax (3-4) 1,583.05 |   545.56 | 1,903.07

COLUMN PROOF (§58): in EACH filing, two of the three quarterly columns reproduce values we already
store -- Dec-2025 revC 779.67 and patC 54.56 in both documents, plus Mar-2026 revC 1089.83 and patC
158.31 in the second. The mapping is demonstrated by the document, not assumed, and the two filings
agree with each other on the overlapping Dec-2025 column.

Cross-checked against screener's consolidated series: 951/190 for Mar-2025, 786/94 for Sep-2025,
683/78 for Dec-2024 -- consistent with the filing to the crore.

NOT WRITTEN HERE:
  * Dec-2024 patC -- the PAT row in the Dec-2025 filing truncates before that column; screener says
    78 but no filing figure was read, so it stays open rather than take a rounded number for a PAT.
  * Jun-2025 (both) -- printed in neither filing; it needs the Jun-2026 filing, which BSE would not
    serve during this run.

Run: python -X utf8 scripts/fill2020_tools/apply_timken_con.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
JOURNAL = os.path.join(SCRIPTS, "con_copy_heals.json")

SRC = "TIMKEN Dec-2025 filing p5 / Mar-2026 filing p16, consolidated statement"
# qe -> (revC, patC, was_patC, note)
CELLS = {
    "20250331": (
        951.46,
        190.31,
        186.83,
        (
            "Mar-2026 filing p16 col3; same row set reproduces Mar-2026 (1089.83/158.31) and "
            "Dec-2025 (779.67/54.56), both already stored"
        ),
    ),
    "20250930": (
        786.35,
        93.60,
        89.47,
        "Dec-2025 filing p5 col2; same row set reproduces Dec-2025 (779.67/54.56), stored",
    ),
    # Dec-2024 revC was NOT empty -- it held 671.40 against a standalone 671.43, i.e. the same copy
    # defect on the REVENUE side. The filing's consolidated column says 683.35. Corrected, not filled.
    "20241231": (
        683.35,
        None,
        None,
        (
            "Dec-2025 filing p5 col3; stored revC 671.40 was a copy of revS 671.43. PAT row "
            "truncates before this column so patC (74.31, also a copy; screener con 78) stays open"
        ),
    ),
}
REV_SLOT, PATC_SLOT = 1, 5  # sf_revop: [revS, revC, opS, opC, patS, patC, ...]
FUND_PATC = 3  # sf_fundamentals row: [qe, patS, annS, patC, annC]


def main():
    dry = "--apply" not in sys.argv
    journal = {}
    revop_paths = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
    fund_paths = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))

    for path in revop_paths:
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        n = 0
        for qe, (rev, pat, was, note) in CELLS.items():
            row = (d.get("TIMKEN") or {}).get(qe)
            if not row:
                print("  %-30s %s no row" % (os.path.basename(path), qe))
                continue
            while len(row) < 9:
                row.append(None)
            cur_rev = row[REV_SLOT]
            std_rev = row[0]
            # write when empty, OR when the con slot is a COPY of the standalone value
            copy = (
                cur_rev is not None
                and std_rev is not None
                and abs(cur_rev - std_rev) <= max(0.05, abs(std_rev) * 0.001)
            )
            if rev is not None and (cur_rev is None or copy):
                row[REV_SLOT] = rev
                n += 1
                journal[f"TIMKEN|{qe}|revC"] = {
                    "now": rev,
                    "was": cur_rev,
                    "src": SRC,
                    "evidence": note,
                    "reason": ("con revenue slot held a COPY of standalone" if copy else "cell was empty"),
                    "applied": "2026-08-09",
                }
            if pat is not None and row[PATC_SLOT] is not None and abs(row[PATC_SLOT] - was) <= 0.02:
                row[PATC_SLOT] = pat
                n += 1
            d["TIMKEN"][qe] = row
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s %d cells" % (os.path.basename(path), "would set" if dry else "set", n))

    for path in fund_paths:
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        n = 0
        for r in d.get("TIMKEN", []):
            qe = str(r[0])
            if qe not in CELLS:
                continue
            rev, pat, was, note = CELLS[qe]
            if pat is None or len(r) <= FUND_PATC:
                continue
            if r[FUND_PATC] is None or abs(r[FUND_PATC] - was) > 0.02:
                print(f"  skip fund {qe}: holds {r[FUND_PATC]}, expected the copied {was}")
                continue
            r[FUND_PATC] = pat
            n += 1
            journal[f"TIMKEN|{qe}|patC"] = {
                "now": pat,
                "was": was,
                "src": SRC,
                "evidence": note,
                "reason": "con slot held the STANDALONE value; TIMKEN filed standalone-only until Dec-2025",
                "applied": "2026-08-09",
            }
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s %d PAT cells" % (os.path.basename(path), "would fix" if dry else "fixed", n))

    for k, v in sorted(journal.items()):
        print("   %-24s %s -> %s" % (k, v.get("was"), v["now"]))
    if dry:
        print("DRY RUN -- nothing written.")
        return
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s (reversible)" % (len(journal), os.path.basename(JOURNAL)))


if __name__ == "__main__":
    main()
