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
"""Fill empty quarters derived from screener's FY ANNUAL total minus the three stored siblings.

This is the cheap route for PRE-2020, and the only one that reaches there at all: screener's
quarterly table holds ~13 quarters, so it cannot see a 2018 quarter -- but its ANNUAL P&L goes back
to FY2015, and a published year total minus three quarters we already store IS the fourth quarter.
Arithmetic on a published figure, not an estimate. No PDF fetch, no vision, no filing read.

The derivation and its gates live in screener_annual_sweep.py:
  GATE A   our own 4-quarter sums must reproduce screener's annual on >=3 OTHER years (>=60%),
           which proves the two sides are the same entity on the same basis;
  GATE A2  the FY being derived from must not itself be restated, nor adjacent to a restated year
           -- screener carries restated totals while our quarters are as-reported, and subtracting
           one from the other yields a plausible-looking garbage residual;
  GATE B   the residual must be positive and within [0.2x, 5x] of the median sibling quarter.

This applier adds:
  * CONFIDENCE FLOOR -- `low` means the FY had no comparable neighbour year to bracket it, so
    GATE A2 could not actually be tested. Those are held, not written.
  * fill-only: an occupied cell is never overwritten;
  * a same-basis neighbour-band re-check against the CURRENT data, since the dataset has moved
    since the sweep ran.

Values are crore-rounded (screener rounds its annuals), and journalled as such so a later pass can
refine them from the filing.

  python -X utf8 scripts/fill2020_tools/apply_annual_derived.py [--apply] [--min-conf medium]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER_DATA = os.path.join(SCRIPTS, "revop_fundamentals.json")
JOURNAL = os.path.join(SCRIPTS, "annual_derived_fills.json")
SLOT = {"revS": 0, "revC": 1}
RANK = {"high": 3, "medium": 2, "low": 1}


def band(revop, sym, qe, field):
    slot = SLOT[field]
    have = []
    for q, row in (revop.get(sym) or {}).items():
        if int(q) == qe or not row or len(row) <= slot or row[slot] is None or row[slot] <= 0:
            continue
        have.append((abs(int(q) - qe), row[slot]))
    vals = sorted(v for _d, v in sorted(have)[:8])
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def main():
    dry = "--apply" not in sys.argv
    floor = sys.argv[sys.argv.index("--min-conf") + 1] if "--min-conf" in sys.argv else "medium"
    derived = json.load(open("/tmp/annual_derive.json"))["derived"]
    revop = json.load(open(DOCS))

    ok, skip = [], []
    for key, rec in sorted(derived.items()):
        sym, qe, field = key.split("|")
        slot = SLOT[field]
        conf = rec.get("confidence", "low")
        if RANK.get(conf, 0) < RANK[floor]:
            skip.append((key, f"confidence {conf} below floor {floor} (FY not bracketed)"))
            continue
        row = (revop.get(sym) or {}).get(qe)
        if not row or len(row) <= slot:
            skip.append((key, "no row"))
            continue
        if row[slot] is not None:
            skip.append((key, f"cell already filled ({row[slot]})"))
            continue
        val = rec["value"]
        if val is None or val <= 0:
            skip.append((key, "derived value not positive"))
            continue
        med = band(revop, sym, int(qe), field)
        if med and not (0.2 * med <= val <= 5 * med):
            skip.append((key, f"{val:.2f} outside [0.2x,5x] of current neighbour median {med:.2f}"))
            continue
        ok.append((sym, qe, field, val, conf, rec))

    print("derived %d | WOULD FILL %d | held %d\n" % (len(derived), len(ok), len(skip)))
    print("by year :", dict(sorted(collections.Counter(q[:4] for _s, q, _f, _v, _c, _r in ok).items())))
    print("by field:", dict(collections.Counter(f for _s, _q, f, _v, _c, _r in ok)))
    print("by conf :", dict(collections.Counter(c for _s, _q, _f, _v, c, _r in ok)))
    for sym, qe, field, val, conf, rec in ok[:25]:
        print("  %-12s %-9s %-5s = %-11.2f %-7s %s" % (sym, qe, field, val, conf, rec["src"][:44]))
    if dry:
        print("\nDRY RUN -- nothing written.")
        return

    journal = {}
    for path in (DOCS, LEDGER_DATA):
        d = json.load(open(path))
        n = 0
        for sym, qe, field, val, conf, rec in ok:
            row = (d.get(sym) or {}).get(qe)
            if not row:
                continue
            while len(row) < 9:
                row.append(None)
            if row[SLOT[field]] is not None:
                continue
            row[SLOT[field]] = val
            d[sym][qe] = row
            n += 1
            journal[f"{sym}|{qe}|{field}"] = {
                field: val,
                "precision": "crore-rounded",
                "src": "screener.in FY annual minus the three stored quarters",
                "evidence": rec["src"],
                "fy_total": rec.get("fy_total"),
                "siblings": rec.get("others"),
                "confidence": conf,
                "applied": "2026-08-07 annual-derivation fill",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s filled %d" % (os.path.basename(path), n))
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(journal), os.path.basename(JOURNAL)))


if __name__ == "__main__":
    main()
