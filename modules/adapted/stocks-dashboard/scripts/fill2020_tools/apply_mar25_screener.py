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
"""FILL-2020: the Mar-2025 residual, closed via the screener.in route + filing refinement.

WHY THIS BATCH EXISTS. Every one of these cells had been reported by me as unfillable. They were
not. screener.in held all of them. The failure was mine: I only ever read FILINGS, and when a
filing was image-only (MCX), used an unexpected row label (AIIL's finance layout says "Revenue",
not "Sales"), or interleaved bases on one page (BALKRISIND), my reader returned nothing and I wrote
that up as "the data does not exist". A second opinion existed the whole time. Route ladder §57
gains rung 3b for exactly this reason.

METHOD, per cell (all three steps required):
  1. screener.in quarterly table, read from HTML with data-date-key column addressing -- the column
     is chosen by PRINTED DATE, never by index (§55b). The prose/WebFetch route is BANNED here: it
     mis-shifted CYIENT by one column (claimed Mar-25 = 1927, actual 1909, and 1926.4 is our own
     stored Dec-24 -- an off-by-one that would have written the wrong quarter's revenue).
  2. GATE: screener's own series must reproduce >=2 of our stored values for the same field with
     ZERO disagreements. Rejected TMPV on this rule (screener shows the demerged PV-only company;
     our series is legacy Tata Motors incl. JLR through Jun-2025 -- they only converge from
     Sep-2025). A blind copy would have silently corrupted 4 quarters.
  3. REFINE: screener prints crore-rounded integers, so it is the SEARCH KEY, not the answer. Where
     the filing (own quarter, or the next-year / next-quarter comparative column) yields the exact
     figure within +-1 of the target, the exact figure is stored and marked filing-exact. Where BSE
     was throttling at run time, the crore-rounded value is stored and MARKED crore-rounded so a
     later pass can refine it -- a sourced approximation with honest provenance beats a hole.

  sym         value      precision      how
  AIIL        1452.0     crore-rounded  screener 'Revenue' row (NBFC layout); gate 11/11
  BALKRISIND  2752.38    filing-exact   own filing p2 'Revenue from Operations'; std twin is 2746.59
  CGPOWER     2752.77    filing-exact   Mar-2026 filing p16 comparative '(a) Revenue from operations'
  CYIENT      1909.0     crore-rounded  gate 12/12; BSE announcement API throttled at run time
  KNRCON      975.0      crore-rounded  gate 12/12; filing 'Total income' = 975.21 (incl. other
                                        income, so NOT written as revenue-from-operations)
  MCX         291.33     filing-exact   vision read, Mar-2026 filing image page; the SAME page whose
                                        Dec-2025 column reproduced our stored con PAT 401.12 AND con
                                        revenue 665.62 exactly, so the column mapping is proven
  NMDC        7004.59    filing-exact   Mar-2026 filing p24 'Sales / Income from Operations'
  SWANCORP    855.75     filing-exact   own filing p8 'Total Income from Operations' 85,575.3 lakh;
                                        con PAT -17.73 confirmed on p5. Gate FAILED here only
                                        because OUR stored 2024-03-31 revC is 7.91 against
                                        screener's 1398 -- our cell is the wrong one (logged below).
  WAAREEENER  4004.0     crore-rounded  gate 11/11; BSE throttled at run time
  WESTLIFE    0.29       filing-exact   Jun-2025 filing p3 preceding-quarter col, 28.94 lakh (revS)

NOT WRITTEN: TMPV 2025-03-31 revC -- entity break, needs the legacy Tata Motors consolidated filing.
SUSPECT CELL FOUND: SWANCORP 2024-03-31 revC = 7.91 vs screener 1398, with Jun/Sep/Dec-2024 all
matching to the paisa. Almost certainly a bad row/scale read. Logged, not silently patched.

Fill-only: an already-populated cell is never overwritten.
Run: python -X utf8 scripts/fill2020_tools/apply_mar25_screener.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")
QE = "20250331"

CELLS = {
    "AIIL": ("revC", 1452.0, "crore-rounded", "screener.in gate 11/11, row 'Revenue' (NBFC layout)"),
    "BALKRISIND": (
        "revC",
        2752.38,
        "filing-exact",
        "own BSE filing p2 'Revenue from Operations'; screener target 2752",
    ),
    "CGPOWER": (
        "revC",
        2752.77,
        "filing-exact",
        "Mar-2026 filing p16 comparative '(a) Revenue from operations'; screener target 2753",
    ),
    "CYIENT": ("revC", 1909.0, "crore-rounded", "screener.in gate 12/12; BSE announcement API throttled at run time"),
    "KNRCON": (
        "revC",
        975.0,
        "crore-rounded",
        "screener.in gate 12/12; filing 'Total income' 975.21 includes other income",
    ),
    "MCX": (
        "revC",
        291.33,
        "filing-exact",
        "vision read of Mar-2026 image page; same page's Dec-2025 column reproduces stored con PAT 401.12 and con rev 665.62",
    ),
    "NMDC": (
        "revC",
        7004.59,
        "filing-exact",
        "Mar-2026 filing p24 'Sales / Income from Operations'; screener target 7005",
    ),
    "SWANCORP": (
        "revC",
        855.75,
        "filing-exact",
        "own filing p8 'Total Income from Operations' 85,575.3 lakh; con PAT -17.73 confirmed p5; screener 856",
    ),
    "WAAREEENER": (
        "revC",
        4004.0,
        "crore-rounded",
        "screener.in gate 11/11; BSE announcement API throttled at run time",
    ),
    "WESTLIFE": ("revS", 0.29, "filing-exact", "Jun-2025 filing p3 preceding-quarter column, 28.94 lakh"),
}
SLOT = {"revS": 0, "revC": 1}


def main():
    dry = "--apply" not in sys.argv
    wrote, skipped = 0, []
    journal = {}
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        n = 0
        for sym, (field, val, prec, ev) in sorted(CELLS.items()):
            row = (d.get(sym) or {}).get(QE)
            if row is None:
                skipped.append(f"{sym}: no {QE} row in {os.path.basename(path)}")
                continue
            while len(row) < 9:
                row.append(None)
            i = SLOT[field]
            if row[i] is not None:
                skipped.append(f"{sym} {field} already = {row[i]} ({os.path.basename(path)})")
                continue
            row[i] = val
            d[sym][QE] = row
            n += 1
            journal[f"{sym}|{QE}"] = {
                field: val,
                "precision": prec,
                "src": "screener.in + filing refine (route §57 rung 3b)",
                "evidence": ev,
                "applied": "2026-08-06 Mar-2025 sweep",
            }
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s %d cells" % (os.path.basename(path), "would fill" if dry else "filled", n))
        wrote = max(wrote, n)
    for s in skipped:
        print(f"  skip: {s}")
    if not dry and journal:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(journal)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))
    if dry:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
