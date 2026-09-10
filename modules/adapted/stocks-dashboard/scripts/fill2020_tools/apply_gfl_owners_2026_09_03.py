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
"""GFLLIMITED (ex-Gujarat Fluorochemicals): put the 3 Ind-AS-era consolidated PAT cells that
stored the TOTAL "Profit for the period" onto the OWNERS-attributable convention.

BACKGROUND (session 2026-09-03, G1 heal). GFLLIMITED is the holding company that consolidated
Inox Leisure + Inox Wind (large, often loss-making minorities). Under Ind-AS the filing prints an
explicit attribution block:  Profit for the period (TOTAL) = Owners of the Company + NCI.
For FY2017Q4..FY2018Q3 our con slot (sf_fundamentals idx3) stored the TOTAL, not owners. Every
OTHER GFL con quarter already stores owners:
  * pre-Ind-AS 2013Q1..2016Q4 stored `period - minority - assoc` (owners), verified from the NSE
    archive detail pages against each quarter's OWN filing;
  * 2018Q4..2026Q1 store `ProfitOrLossAttributableToOwnersOfParent` (verified tag-exact in each
    quarter's own consolidated XBRL, identity owners+NCI==total closing);
  * 2012Q1..2013Q1 filed NO quarterly consolidated statement at all (standalone-only / annual-only
    con) so their stored con is aggregator-derived and out of scope -- LEFT, logged.

The 3 healed cells were read from GFLLIMITED's OWN audited/reviewed consolidated result PDF filed
to BSE, from the EXPLICIT "Profit/(Loss) for the period attributable to: Owners of the Company"
line (NOT reconstructed -- the NSE-archive "Minority interest" line is the TOTAL-COMPREHENSIVE-
INCOME attribution, off by the NCI share of OCI, which is exactly why the reconstruction gave
-122.04/71.12/69.76 instead of the filed -122.20/71.49/70.19). Unit = Rs. Lakhs.

Gates that held for every healed cell (§116c identity gate):
  (a) owners + NCI == total to the lakh, on the filing's own attribution block;
  (b) the standalone result for the same quarter reproduces our stored std PAT (GATE S', §53a);
  (c) our stored con reproduces the filing's TOTAL "Profit for the period" row (defect signature).

  qe        stored(total)   owners      NCI    filing (BSE attachment, page)
  20170331     -75.09     -122.20     47.11    21cf451d... Q4FY17 audited con P&L (Owners (12,220)L + NCI 4,711L = (7,509)L)
  20170930      59.77       71.49    -11.73    0d3ef425... Q2FY18 con P&L      (Owners 7,149L + NCI (1,173)L = 5,976L)
  20171231      59.47       70.19    -10.74    7b04de95... Q3FY18 con P&L      (Owners 7,019L + NCI (1,074)L = 5,945L)

std GATE S' (NSE archive standalone detail): 20170331 52.43, 20170930 88.74, 20171231 94.66 -- all == stored std.

Writes (all guarded on the stored TOTAL, idempotent, fill-safe merge into existing ledgers):
  * sf_fundamentals idx3 (npCon) in BOTH twins  -> owners
  * sf_revop        idx5 (pat_con mirror) in BOTH twins -> owners
  * scripts/owners_basis_heals.json  (owners key -> apply_owners_full re-asserts idx3 nightly)
  * scripts/revop_cell_fix.json      (basis pat_con -> apply_revop_cell_fix re-asserts idx5 nightly)
Does NOT touch std (idx1/idx4), annCon (idx4), or con revenue (revop idx1).

Run:  python3 -X utf8 scripts/fill2020_tools/apply_gfl_owners_2026_09_03.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
OWN_LEDGER = os.path.join(SCRIPTS, "owners_basis_heals.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_cell_fix.json")
FUND_IDX, REVOP_IDX = 3, 5
SYM = "GFLLIMITED"

# qe -> (stored_total, owners, nci, note)
FIX = {
    20170331: (
        -75.09,
        -122.20,
        47.11,
        "Q4FY17 audited consolidated P&L (BSE 21cf451d...): Owners (12,220)L + NCI 4,711L = (7,509)L total; std 52.43 reproduced.",
    ),
    20170930: (
        59.77,
        71.49,
        -11.73,
        "Q2FY18 consolidated P&L (BSE 0d3ef425...): Owners 7,149L + NCI (1,173)L = 5,976L total; std 88.74 reproduced.",
    ),
    20171231: (
        59.47,
        70.19,
        -10.74,
        "Q3FY18 consolidated P&L (BSE 7b04de95...): Owners 7,019L + NCI (1,074)L = 5,945L total; std 94.66 reproduced.",
    ),
}
SRC = "GFLLIMITED own consolidated result PDF filed to BSE, explicit 'Profit for the period attributable to: Owners of the Company' line (G1 heal 2026-09-03)"
TOL = 0.02


def guard_split():
    for qe, (tot, own, nci, _n) in FIX.items():
        if abs((own + nci) - tot) > 0.03:
            sys.exit("IDENTITY BROKEN %d: owners %.2f + nci %.2f != total %.2f" % (qe, own, nci, tot))


def apply_data(dry):
    n = 0
    for paths, idx, keyed in ((FUND, FUND_IDX, False), (REVOP, REVOP_IDX, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            for qe, (tot, own, _nci, _n) in FIX.items():
                if keyed:
                    row = (d.get(SYM) or {}).get(str(qe))
                else:
                    row = next((r for r in d.get(SYM, []) if r[0] == qe), None)
                if not row or len(row) <= idx:
                    print("  (absent) %-28s %d idx%d" % (os.path.relpath(path, ROOT), qe, idx))
                    continue
                cur = row[idx]
                if cur is not None and abs(cur - own) <= 0.005:
                    continue  # already owners (idempotent)
                if cur is None or abs(cur - tot) > TOL:
                    sys.exit(
                        "GUARD %s %d idx%d: current %s, expected stored total %.2f -- refusing"
                        % (os.path.basename(path), qe, idx, cur, tot)
                    )
                print("  %-28s %d idx%d: %.2f -> %.2f" % (os.path.relpath(path, ROOT), qe, idx, cur, own))
                if not dry:
                    row[idx] = own
                n += 1
            if not dry:
                tmp = path + ".tmp"
                json.dump(d, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
                os.replace(tmp, path)
    return n


def merge_owners_ledger(dry):
    L = json.load(open(OWN_LEDGER, encoding="utf-8"))
    cells = L.setdefault("cells", {})
    for qe, (tot, own, nci, note) in FIX.items():
        cells["%s|%d|patC" % (SYM, qe)] = {
            "found_by": "G1 GFL owners-basis heal 2026-09-03 (Ind-AS attribution block, explicit owners line)",
            "nci": nci,
            "owners": own,
            "total_was": tot,
            "note": note,
            "src": SRC,
        }
    rd = L.get("_README")
    line = (
        "2026-09-03 (G1): GFLLIMITED 20170331/20170930/20171231 con PAT held the TOTAL 'Profit for the "
        "period' where every neighbouring quarter stores owners; healed to owners from each quarter's OWN "
        "BSE consolidated attribution block (Owners (12,220)/7,149/7,019 L). Identity owners+NCI==total and "
        "GATE S' (std 52.43/88.74/94.66) both close. 2012Q1-2013Q1 filed no quarterly con statement -> LEFT."
    )
    if isinstance(rd, list) and line not in rd:
        rd.append(line)
    if not dry:
        tmp = OWN_LEDGER + ".tmp"
        json.dump(L, open(tmp, "w", encoding="utf-8"), indent=1)
        os.replace(tmp, OWN_LEDGER)


def merge_revop_ledger(dry):
    L = json.load(open(REVOP_LEDGER, encoding="utf-8"))
    fixes = L.setdefault("fixes", [])
    have = {(f.get("sym"), str(f.get("qe")), f.get("basis")) for f in fixes}
    for qe, (tot, own, _nci, note) in FIX.items():
        key = (SYM, str(qe), "pat_con")
        if key in have:
            continue
        fixes.append(
            {
                "sym": SYM,
                "qe": str(qe),
                "basis": "pat_con",
                "was": tot,
                "fixed": own,
                "why": (
                    "§70 PAT mirror sync to the owners-basis heal of sf_fundamentals npCon (G1 2026-09-03). " + note
                ),
            }
        )
    if not dry:
        tmp = REVOP_LEDGER + ".tmp"
        json.dump(L, open(tmp, "w", encoding="utf-8"), indent=1)
        os.replace(tmp, REVOP_LEDGER)


def main():
    dry = "--apply" not in sys.argv
    guard_split()
    print("== data files ==")
    n = apply_data(dry)
    print("== ledgers ==")
    merge_owners_ledger(dry)
    merge_revop_ledger(dry)
    print(
        "\n%d data slot(s) %s; ledgers %s"
        % (n, "would change (dry)" if dry else "changed", "unchanged (dry)" if dry else "updated")
    )
    if dry:
        print("(pass --apply)")


if __name__ == "__main__":
    main()
