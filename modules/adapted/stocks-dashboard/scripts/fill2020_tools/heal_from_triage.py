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
"""Apply the CUMULATIVE / FY-IN-QUARTER corrections from triage_suspects.py. Corrections, not fills.

Only the buckets whose correct value falls out of arithmetic are written here. SCALE goes through
scripts/scale_fix.json (its own reviewed ledger, keyed on the filing). RUN and ISOLATED-DIFF are
never auto-corrected: a RUN means the two sides measure different things, and an ISOLATED-DIFF has
no derivable answer.

GUARDS, each must pass or the cell is skipped loudly:
  * the cell still holds the value the correction was computed against (another writer, or a
    rebuild, may have changed it since the audit snapshot -- FRETAIL was already healed by an
    earlier pass and is correctly skipped here);
  * the replacement is > 0 (a negative residual means one of the SIBLING quarters is the wrong one,
    not this cell -- reported, not written);
  * the replacement is strictly smaller than what it replaces, since a cumulative contains the
    quarter;
  * the change is at least 15% -- a correction inside rounding noise was never a cumulative.

Journals old -> new per cell to scripts/cumulative_heals.json (shared with the first heal pass), so
every correction stays reversible and auditable.

  python -X utf8 scripts/fill2020_tools/heal_from_triage.py [--apply]
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
JOURNAL = os.path.join(SCRIPTS, "cumulative_heals.json")
SLOT = {"revS": 0, "revC": 1}
BUCKETS = ("CUMULATIVE", "FY-IN-QUARTER")


def main():
    dry = "--apply" not in sys.argv
    verdicts = json.load(open("/tmp/triage_verdicts.json"))
    revop = json.load(open(DOCS))

    ok, skip = [], []
    for r in verdicts:
        if r["bucket"] not in BUCKETS:
            continue
        sym, qe, field = r["sym"], str(r["qe"]), r["field"]
        new = r.get("suggested")
        slot = SLOT[field]
        row = (revop.get(sym) or {}).get(qe)
        cur = row[slot] if row and len(row) > slot else None
        if cur is None or not (abs(cur - r["ours"]) <= 0.02):
            skip.append((sym, qe, field, "cell now holds {}, audit saw {}".format(cur, r["ours"])))
            continue
        if new is None or new <= 0:
            skip.append(
                (sym, qe, field, (f"residual {new} not positive -- a SIBLING quarter is the wrong one, not this cell"))
            )
            continue
        if new >= cur:
            skip.append((sym, qe, field, f"replacement {new} not smaller than {cur}"))
            continue
        if abs(new - cur) < 0.15 * abs(cur):
            skip.append((sym, qe, field, f"change {cur:.2f} -> {new:.2f} is within noise"))
            continue
        ok.append((sym, qe, field, cur, new, r["bucket"], r["reason"]))

    for s, q, f, c, n, b, why in ok:
        print("  HEAL %-12s %-9s %-5s %13.2f -> %-12.2f %-14s %s" % (s, q, f, c, n, b, why[:44]))
    for s, q, f, w in skip:
        print("  skip %-12s %-9s %-5s %s" % (s, q, f, w))
    print("\nwould heal %d, skipped %d" % (len(ok), len(skip)))
    print("by quarter:", dict(sorted(collections.Counter(q for _s, q, _f, _c, _n, _b, _w in ok).items())))
    if dry:
        print("DRY RUN -- nothing written.")
        return

    journal = {}
    for path in (DOCS, LEDGER_DATA):
        d = json.load(open(path))
        n = 0
        for sym, qe, field, cur, new, bucket, why in ok:
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
                "reason": bucket,
                "evidence": why,
                "applied": "2026-08-07 triage heal",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s healed %d" % (os.path.basename(path), n))
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s (reversible)" % (len(journal), os.path.basename(JOURNAL)))


if __name__ == "__main__":
    main()
