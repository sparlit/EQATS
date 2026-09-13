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
"""Null CONSOLIDATED cells for quarters where the company filed NO consolidated result at all.

THE DEFECT, and why the existing purge could not see it. `purge_copied_con.py` nulls a con cell
that EXACTLY EQUALS its standalone twin -- that equality is the byte-copy signature (runbook
85a-ter). The cells this script removes DIFFER from standalone, so they survived that purge. But
"differs" only proves "not a byte copy"; it never proves "a consolidated table exists". Where the
exchange record shows no consolidated filing for the quarter, ANY con value is fabricated no matter
how it compares to standalone.

HUHTAMAKI is the worked example (found 2026-08-18). It stopped filing consolidated after QE
2016-12-31, yet carried a revC for 22 quarters from 2020-12 to 2026-03, every one slightly BELOW
revS -- because the stored "consolidated revenue" is the STANDALONE statement's revenue sub-line
"a) Sale of Products & Services". Read off the company's own Dec-2022 PDF: sub-line 6,765.2 Mn
(= stored revC 676.52) vs Total Revenue from Operations 6,927.1 Mn (= stored revS 692.71), and
676.52 + 16.19 Other Operating Revenue = 692.71 to the paisa. One cell was not even that: 20241231
carried a byte-copy of 20240930's sub-line while the Dec-2024 filing prints 6,012.3 Mn.

Every cell removed here is journalled in scripts/con_nofile_retractions.json with the value taken
away, its standalone twin, and the reason -- and each entry carries `held`, so
verify_fills_live.py's resurrection check (runbook 85b) asserts the cell stays ABSENT and reports
it if any applier refills it. A retraction that is not pinned in every ledger that could refill it
gets silently undone (runbook 85a); this script plus that registration is the pin.

SAFETY. A cell is nulled only when the live value still MATCHES the value the ledger recorded. If
it has moved, the cell is reported as CHANGED and left alone -- a moved value means either a real
consolidated filing has since landed or another writer owns the cell, and retracting on a stale
flag deletes correct data (runbook 85a-bis). Re-running is a no-op once applied.

Run:  python3 scripts/apply_con_nofile_retractions.py [--apply]
Exit code 1 if any ledger cell is CHANGED (needs a human), else 0.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "con_nofile_retractions.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_M = os.path.join(HERE, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
FUND_M = os.path.join(HERE, "fundamentals.json")

# sf_revop row: [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC]
SLOT = {"revC": 1, "opC": 3, "patC": 5, "ebitC": 8}
TOL = 0.011


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save(p, d):
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(d, fh, separators=(",", ":"))


def main():
    apply_it = "--apply" in sys.argv
    led = load(LEDGER)
    cells = [(k, v) for k, v in led.items() if not k.startswith("_")]

    nulled, already, changed = [], [], []
    for path in (REVOP, REVOP_M):
        d = load(path)
        n = 0
        for key, ent in cells:
            sym, qe, field = key.split("|")
            slot = SLOT.get(field)
            if slot is None:
                continue
            row = (d.get(sym) or {}).get(qe)
            if not row or len(row) <= slot:
                continue
            cur = row[slot]
            if cur is None:
                if path == REVOP:
                    already.append(key)
                continue
            if abs(cur - ent["was"]) > TOL:
                if path == REVOP:
                    changed.append((key, ent["was"], cur))
                continue
            row[slot] = None
            n += 1
            if path == REVOP:
                nulled.append((key, cur))
        if apply_it:
            save(path, d)
        print("%-30s con cells nulled: %d" % (os.path.basename(path), n))

    # sf_revop patC is a MIRROR of sf_fundamentals npCon (runbook 70) -- keep the two stores
    # consistent, or a retraction empties one while the same figure stays live in the other
    # (runbook 85a-bis). Already null for every cell in the ledger today; this guards the future.
    pats = {(k.split("|")[0], int(k.split("|")[1])): v for k, v in cells if k.split("|")[2] == "patC"}
    for path in (FUND, FUND_M):
        if not os.path.exists(path):
            continue
        d = load(path)
        n = 0
        for (sym, qe), ent in pats.items():
            for r in d.get(sym, []):
                if r[0] != qe or len(r) < 4 or r[3] is None:
                    continue
                if abs(r[3] - ent["was"]) > TOL:
                    continue
                r[3] = None
                if len(r) > 4:
                    r[4] = None
                n += 1
        if apply_it:
            save(path, d)
        print("%-30s conPAT nulled: %d" % (os.path.basename(path), n))

    # docs/fin/<SYM>.json is what the stock page actually reads. build_stock_fin.py regenerates it
    # from sf_revop, but it rebuilds all ~4,600 symbols at once and a local run bakes in whatever
    # stale sf_stock_data.bin the checkout happens to hold — so heal the two files in place and let
    # CI's next full build agree, rather than committing a whole-universe rebuild.
    fin_n = 0
    bysym = {}
    for key, ent in cells:
        bysym.setdefault(key.split("|")[0], []).append((key, ent))
    for sym, entries in bysym.items():
        fp = os.path.join(ROOT, "docs", "fin", f"{sym}.json")
        if not os.path.exists(fp):
            continue
        d = load(fp)
        hit = 0
        for key, ent in entries:
            _, qe, field = key.split("|")
            slot = SLOT.get(field)
            row = (d.get("revop") or {}).get(qe)
            if slot is None or not row or len(row) <= slot or row[slot] is None:
                continue
            if abs(row[slot] - ent["was"]) > TOL:
                continue
            row[slot] = None
            hit += 1
        fin_n += hit
        if apply_it and hit:
            save(fp, d)
    print("%-30s con cells nulled: %d" % ("docs/fin/<SYM>.json", fin_n))

    print()
    # counts below are sf_revop's; the per-file lines above carry each store's own tally
    print(
        "ledger cells: %d   sf_revop nulled now: %d   already absent: %d   CHANGED: %d%s"
        % (
            len(cells),
            len(nulled),
            len(already),
            len(changed),
            "" if apply_it else "      (DRY RUN -- pass --apply to write)",
        )
    )
    for key, val in nulled:
        print("   nulled   %-28s was %s" % (key, val))
    for key, was, cur in changed:
        print("   CHANGED  %-28s ledger recorded %s, live value is %s -- LEFT ALONE, needs a human" % (key, was, cur))
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
