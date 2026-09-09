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
"""Gate and apply the universal_read sweep. Reading a number is not the same as trusting it.

The reader anchors every value on our own stored PAT at a geometric column (§62), which rules out
wrong-quarter and wrong-basis reads. It does NOT rule out wrong-ROW: on a page where no operating
line matched, the last-resort labels "Total income" / "Total revenue" win by default, and those
include other income. So three further gates before anything is written:

  G1 NEIGHBOUR BAND. Value must sit in [0.2x, 5x] of the median stored revenue for this company on
     THIS basis across the 8 nearest quarters. Same rule as nse_xbrl_rev.py, and deliberately NOT
     against the other basis' twin -- con/std ratios are legitimately huge for holding structures.

  G2 ROW CLASS. A value read from a "total income"/"total revenue"/"total" row is TOTAL-INCOME
     class, not revenue-from-operations. It is held back for review unless G3 independently
     confirms it, because the difference is silent and permanent.

  G3 INDEPENDENT CROSS-CHECK (screener.in, §60). Where screener covers the quarter, its figure must
     agree within 1%. Where it does not (older than ~13 quarters), the FY identity is used instead:
     our three stored siblings + this value must reproduce screener's annual total for that FY,
     which is a genuinely independent constraint on the number being read.
     A DISAGREEMENT REJECTS. Absence of screener coverage is not a rejection, it is just no vote.

Every write records which gates voted and how. Fill-only; an occupied cell is never touched.

  python -X utf8 scripts/fill2020_tools/apply_sweep.py /tmp/sweep.json [--apply]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF  # noqa: E402

REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "sweep_rev_fills.json")
SLOT = {"revS": 0, "revC": 1}
TOTAL_ROW = re.compile(r"t[o0]tal\s+(inc[o0]me|revenue)|^\s*t[o0]tal\b", re.IGNORECASE)
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}
BAND_LO, BAND_HI, NEIGH = 0.2, 5.0, 8


def fy_quarters(fy_end):
    y = fy_end // 10000
    return [(y - 1) * 10000 + 630, (y - 1) * 10000 + 930, (y - 1) * 10000 + 1231, y * 10000 + 331]


def main():
    sweep = json.load(open(sys.argv[1]))
    dry = "--apply" not in sys.argv
    revop = json.load(open(REVOP_DOCS))
    hits = {k: v for k, v in sweep.items() if v.get("state") == "FILLED-EXACT"}
    print("read %d cells; gating\n" % len(hits))

    accept, review, reject = {}, [], []
    scr_cache = {}
    for key, r in sorted(hits.items()):
        sym, qe, field = key.split("|")
        qe = int(qe)
        slot = SLOT[field]
        val = r["value"]
        ev = r.get("evidence") or {}
        mine = {
            int(q): row[slot]
            for q, row in (revop.get(sym) or {}).items()
            if row and len(row) > slot and row[slot] is not None and row[slot] > 0
        }
        # ---- G1 neighbour band
        near = [v for _d, v in sorted((abs(q - qe), v) for q, v in mine.items())[:NEIGH]]
        if not near:
            reject.append((key, val, "G1 no same-basis neighbour to band against"))
            continue
        near.sort()
        med = near[len(near) // 2] if len(near) % 2 else (near[len(near) // 2 - 1] + near[len(near) // 2]) / 2.0
        if not (BAND_LO * med <= val <= BAND_HI * med):
            reject.append((key, val, f"G1 band: {val:.2f} vs median {med:.2f}"))
            continue
        # ---- G2 row class
        total_class = bool(TOTAL_ROW.search(ev.get("rev_row", "")))
        # ---- G3 independent cross-check
        con = field.endswith("C")
        ck = (sym, con)
        if ck not in scr_cache:
            scr_cache[ck] = (SF.quarters(sym, con=con), SF.annuals(sym, con=con))
        sq, sa = scr_cache[ck]
        label = next((L for L in ("Sales", "Revenue") if any(L in row for row in (sq or {}).values())), "Sales")
        dk = "%d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        vote, why = None, "no screener coverage"
        theirs = (sq.get(dk) or {}).get(label) if sq else None
        if theirs is not None:
            vote = abs(val - theirs) <= max(1.0, abs(theirs) * 0.01)
            why = f"screener quarter {dk} = {theirs} vs {val}"
        elif sa:
            alab = next((L for L in ("Sales", "Revenue") if any(L in row for row in sa.values())), None)
            fy = qe if qe % 10000 == 331 else (qe // 10000 + 1) * 10000 + 331
            tot = (sa.get("%d-03-31" % (fy // 10000)) or {}).get(alab) if alab else None
            sibs = [q for q in fy_quarters(fy) if q != qe]
            if tot is not None and all(q in mine for q in sibs):
                s = sum(mine[q] for q in sibs) + val
                vote = abs(s - tot) <= max(2.0, abs(tot) * 0.01)
                why = "FY%d identity: 3 siblings + this = %.2f vs screener annual %s" % (fy // 10000, s, tot)
        if vote is False:
            reject.append((key, val, f"G3 {why}"))
            continue
        rec = {
            field: val,
            "src": "bse-filing-pdf, geometric column (§62)",
            "evidence": ev,
            "gates": {
                "band_median": round(med, 2),
                "row_class": "total-income" if total_class else "operating",
                "crosscheck": why,
                "crosscheck_pass": vote,
            },
        }
        if total_class and vote is not True:
            review.append((key, val, f"G2 total-income row, unconfirmed ({why})"))
            continue
        accept[key] = rec

    print(
        "ACCEPT %d   REVIEW %d   REJECT %d" % (len({k for k in accept if k.count("|") == 2}), len(review), len(reject))
    )
    for k, v, w in reject[:12]:
        print("  reject  %-28s %-11s %s" % (k, v, w))
    for k, v, w in review[:12]:
        print("  review  %-28s %-11s %s" % (k, v, w))

    if dry:
        print("\nDRY RUN -- nothing written.")
        return
    journal, n = {}, 0
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for key, rec in accept.items():
            if key.count("|") != 2:
                continue
            sym, qe, field = key.split("|")
            row = (d.get(sym) or {}).get(qe)
            if not row:
                continue
            while len(row) < 9:
                row.append(None)
            i = SLOT[field]
            if row[i] is not None:
                continue
            row[i] = rec[field]
            d[sym][qe] = row
            n += 1
            journal[key] = dict(rec, applied="2026-08-06 universal-read sweep")
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s filled %d" % (os.path.basename(path), n))
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(journal)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()
