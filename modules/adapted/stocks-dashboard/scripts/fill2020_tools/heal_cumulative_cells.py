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
"""Heal quarters that hold a CUMULATIVE figure instead of the quarter. Corrections, not fills.

Found by the screener audit the user asked for. Two shapes, both PROVEN per cell before anything
is written:

  FY-IN-QUARTER  the stored value equals screener's FY TOTAL for that year, to within 2%. The real
                 quarter is then `FY total - the three stored siblings` -- the same annual-minus-3
                 identity the campaign already uses, only applied to correct a cell rather than
                 fill an empty one. 23 cells; FRETAIL Mar-2020 revS stores 20,118.32 against an
                 FY2020 total of 20,118, i.e. the entire year sat in Q4.

  YTD-IN-QUARTER the stored value equals the sum of the earlier stored quarters of that FY plus a
                 plausible quarter. KIRLFER 2024-09-30 revS = 3220.82 = its own Jun-2024 (1553.71)
                 + 1667.11, and screener's Sep-2024 is 1667. Proven by ARITHMETIC ALONE -- the
                 identity holds without reference to any outside source.

Also carries one unrelated but equally provable cell found in the same pass:
  CCAVENUE 2023-06-30 revS = 97.29 against neighbours 608 / 740 / 860 and screener's 697 -- a lost
  leading digit. Written crore-rounded and labelled as such, since the exact filing figure was not
  recovered.

GUARDS -- every one must pass or the cell is skipped, loudly:
  * the cell must still hold exactly the value this heal was computed against (someone else may
    have fixed it first; a rebuild may have changed it);
  * the replacement must be > 0 and within [0.25x, 4x] of the median sibling quarter;
  * the replacement must be strictly smaller than what it replaces (a cumulative is by definition
    larger than the quarter inside it).

Journals old -> new per cell to scripts/cumulative_heals.json, so every correction is reversible
and auditable. Writes to BOTH docs/sf_revop.json and the scripts/revop_fundamentals.json ledger
(CLAUDE.md rule 5).

  python -X utf8 scripts/fill2020_tools/heal_cumulative_cells.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER_DATA = os.path.join(SCRIPTS, "revop_fundamentals.json")
JOURNAL = os.path.join(SCRIPTS, "cumulative_heals.json")
SLOT = {"revS": 0, "revC": 1}
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}

EXTRA = [
    # sym, qe, field, was, becomes, evidence
    (
        "KIRLFER",
        "20240930",
        "revS",
        3220.82,
        1667.11,
        (
            "stored value is EXACTLY Jun-2024 (1553.71) + 1667.11; screener Sep-2024 = 1667. "
            "Year-to-date half-year figure stored as the quarter."
        ),
    ),
    (
        "CCAVENUE",
        "20230630",
        "revS",
        97.29,
        697.0,
        (
            "neighbours 608.25 / 739.91 / 860.26 and screener 697 -- a lost leading digit. "
            "crore-rounded from screener; exact filing figure not recovered."
        ),
    ),
]


def fy_quarters(fy):
    return [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231, fy * 10000 + 331]


def main():
    dry = "--apply" not in sys.argv
    revop = json.load(open(DOCS))
    plan = []

    for rec in json.load(open("/tmp/cumulative_confirmed.json")):
        h, tot = rec["hit"], rec["fy_total"]
        sym, qe, field, fy = h["sym"], str(h["qe"]), h["field"], h["fy"]
        slot = SLOT[field]
        sibs = []
        for q in fy_quarters(fy):
            if str(q) == qe:
                continue
            r = (revop.get(sym) or {}).get(str(q))
            v = r[slot] if r and len(r) > slot else None
            if v is None:
                sibs = None
                break
            sibs.append(v)
        if not sibs:
            continue
        new = round(tot - sum(sibs), 2)
        plan.append(
            (
                sym,
                qe,
                field,
                h["stored"],
                new,
                sorted(sibs),
                "stored %.2f == screener FY%d total %s; real quarter = FY total - the three "
                "stored siblings" % (h["stored"], fy, tot),
                "cumulative",
            )
        )

    for sym, qe, field, was, new, ev in EXTRA:
        r = (revop.get(sym) or {}).get(qe)
        slot = SLOT[field]
        cur = r[slot] if r and len(r) > slot else None
        plan.append((sym, qe, field, cur, new, None, ev, "digit"))

    ok, skip = [], []
    for sym, qe, field, was, new, sibs, ev, kind in plan:
        slot = SLOT[field]
        r = (revop.get(sym) or {}).get(qe)
        cur = r[slot] if r and len(r) > slot else None
        if cur is None or was is None or abs(cur - was) > 0.02:
            skip.append((sym, qe, field, f"cell now holds {cur}, expected {was}"))
            continue
        if not (new > 0):
            skip.append((sym, qe, field, f"replacement {new} not positive"))
            continue
        # A cumulative figure is by definition LARGER than the quarter inside it. Does not apply
        # to the lost-digit case, where the stored value is too SMALL.
        if kind == "cumulative" and new >= cur:
            skip.append((sym, qe, field, f"replacement {new} not smaller than {cur}"))
            continue
        # And a "cumulative" whose correction is within noise was never cumulative -- KERNEX
        # 2.11 -> 2.07 is a 2% rounding difference, not a year parked in a quarter.
        if kind == "cumulative" and abs(new - cur) < 0.15 * abs(cur):
            skip.append((sym, qe, field, f"correction {new:.2f} vs {cur:.2f} is within noise -- not cumulative"))
            continue
        if sibs:
            m = sorted(sibs)[len(sibs) // 2]
            if m > 0 and not (0.25 * m <= new <= 4 * m):
                skip.append((sym, qe, field, f"replacement {new} outside band of sibling median {m}"))
                continue
        ok.append((sym, qe, field, cur, new, ev))

    for s, q, f, c, n, ev in ok:
        print("  HEAL %-12s %-9s %-5s %12.2f -> %-11.2f %s" % (s, q, f, c, n, ev[:52]))
    for s, q, f, why in skip:
        print("  skip %-12s %-9s %-5s %s" % (s, q, f, why))
    print("\nwould heal %d, skipped %d" % (len(ok), len(skip)))
    if dry:
        print("DRY RUN -- nothing written.")
        return

    journal = {}
    for path in (DOCS, LEDGER_DATA):
        d = json.load(open(path))
        n = 0
        for sym, qe, field, cur, new, ev in ok:
            row = (d.get(sym) or {}).get(qe)
            if not row or len(row) <= SLOT[field]:
                continue
            if row[SLOT[field]] is None or abs(row[SLOT[field]] - cur) > 0.02:
                continue
            row[SLOT[field]] = new
            d[sym][qe] = row
            n += 1
            journal[f"{sym}|{qe}|{field}"] = {
                "was": cur,
                "now": new,
                "reason": "cumulative/annual figure stored as a quarter",
                "evidence": ev,
                "applied": "2026-08-06 screener audit heal",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s healed %d" % (os.path.basename(path), n))
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s (reversible)" % (len(journal), os.path.basename(JOURNAL)))


if __name__ == "__main__":
    main()
