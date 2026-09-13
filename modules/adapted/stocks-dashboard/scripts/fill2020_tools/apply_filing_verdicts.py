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
"""Apply the OURS-WRONG verdicts from the filing adjudication.

This is the strongest evidence in the whole audit chain. An OURS-WRONG verdict means the company's
OWN FILING, read with the geometric column reader and anchored on our stored PAT, produced a value
that matches SCREENER and not us. Two independent sources -- the primary document and an outside
reader -- agreeing against our stored cell. It also passed the adjudicator's plausibility guard, so
the read itself is not an outlier against the company's own neighbouring quarters.

The value written is the FILING's figure, not screener's: same number within tolerance, but the
filing carries full precision where screener rounds to the crore.

Standing guards still apply: the cell must still hold what the adjudication saw, and the
replacement must be positive.

  python -X utf8 scripts/fill2020_tools/apply_filing_verdicts.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER_DATA = os.path.join(SCRIPTS, "revop_fundamentals.json")
JOURNAL = os.path.join(SCRIPTS, "filing_verdict_heals.json")
SLOT = {"revS": 0, "revC": 1}


def close(a, b, tol=0.002, floor=0.02):
    return a is not None and b is not None and abs(a - b) <= max(floor, abs(b) * tol)


def main():
    dry = "--apply" not in sys.argv
    adj = json.load(open("/tmp/adjudicated.json"))
    revop = json.load(open(DOCS))

    ok, skip = [], []
    for key, v in sorted(adj.items()):
        if v.get("verdict") != "OURS-WRONG":
            continue
        sym, qe, field = key.split("|")
        slot = SLOT[field]
        row = (revop.get(sym) or {}).get(qe)
        cur = row[slot] if row and len(row) > slot else None
        new = v.get("filing")
        if cur is None or not close(cur, v.get("ours")):
            skip.append((key, "cell now holds {}, adjudication saw {}".format(cur, v.get("ours"))))
            continue
        if new is None or new <= 0:
            skip.append((key, "filing value not positive"))
            continue
        ok.append((sym, qe, field, cur, new, v))

    for sym, qe, field, cur, new, v in ok:
        print("  %-12s %-9s %-5s %13.2f -> %-12.2f  (screener %s)" % (sym, qe, field, cur, new, v.get("screener")))
    for k, w in skip:
        print("  skip %-28s %s" % (k, w))
    print("\nwould heal %d, skipped %d" % (len(ok), len(skip)))
    if dry:
        print("DRY RUN -- nothing written.")
        return

    journal = {}
    for path in (DOCS, LEDGER_DATA):
        d = json.load(open(path))
        n = 0
        for sym, qe, field, cur, new, v in ok:
            row = (d.get(sym) or {}).get(qe)
            if not row or len(row) <= SLOT[field]:
                continue
            if row[SLOT[field]] is None or not close(row[SLOT[field]], cur):
                continue
            row[SLOT[field]] = round(new, 2)
            d[sym][qe] = row
            n += 1
            journal[f"{sym}|{qe}|{field}"] = {
                "was": cur,
                "now": round(new, 2),
                "screener": v.get("screener"),
                "evidence": v.get("evidence"),
                "reason": "filing read (geometric column, PAT-anchored) matches screener, not us",
                "applied": "2026-08-07 filing adjudication",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s healed %d" % (os.path.basename(path), n))
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s (reversible)" % (len(journal), os.path.basename(JOURNAL)))


if __name__ == "__main__":
    main()
