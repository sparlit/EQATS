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
"""Run the screener.in route + validation gate over a list of (sym, qe, field) gaps.

Gate (runbook §57 rung 3b): a screener figure is written ONLY if screener's own series for the SAME
field reproduces at least 2 values we already store, with ZERO disagreements. One disagreement =>
different entity or different basis => the whole series is rejected, never cherry-picked.

Caught by this gate already: TMPV (screener shows the demerged PV-only entity, ours is legacy Tata
Motors incl. JLR) and CYIENT (series will not line up). Blind copying would have corrupted both.

  python -X utf8 scripts/fill2020_tools/screener_gate.py /tmp/mar25.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF  # noqa: E402

# screener prints the top line as "Sales" for industrials but "Revenue" for the finance layout
# (banks/NBFCs/investment companies -- AIIL, and every bank). Gating only on "Sales" is the same
# trap that made the bank-format reads come back empty (§53). Try both, in order.
LABEL = {"rev": ("Sales", "Revenue"), "pat": ("Net Profit",)}


def pick(row, names):
    for n in names:
        if n in row:
            return row[n], n
    return None, None


def ours_series(sym, field):
    """{qe_int: value} for revS/revC (sf_revop slots 0/1) or patS/patC (sf_fundamentals 1/3)."""
    if field.startswith("rev"):
        d = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"))).get(sym) or {}
        i = 0 if field.endswith("S") else 1
        return {int(q): v[i] for q, v in d.items() if v and len(v) > i and v[i] is not None}
    d = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"))).get(sym) or []
    i = 1 if field.endswith("S") else 3
    return {r[0]: r[i] for r in d if len(r) > i and r[i] is not None}


def check(sym, qe, field):
    con = field.endswith("C")
    ser = SF.quarters(sym, con=con)
    if not ser:
        return None, "screener: no quarterly table (%s)" % ("con" if con else "std")
    dk = f"{str(qe)[:4]}-{str(qe)[4:6]}-{str(qe)[6:]}"
    val, label = pick(ser.get(dk) or {}, LABEL[field[:3]])
    if val is None:
        return None, "screener: quarter {} absent (cols {}..{})".format(
            dk, min(ser, default="-"), max(ser, default="-")
        )
    ok, m, n, bad = SF.validate(ser, ours_series(sym, field), label)
    if not ok:
        return None, "GATE FAIL %d/%d agree on %r; %s" % (m, n, label, "; ".join(bad[:2]))
    return val, "gate ok %d/%d neighbour quarters reproduce our stored %s (row %r)" % (m, n, field, label)


def main():
    tg = json.load(open(sys.argv[1]))
    out = {}
    for sym, d in sorted(tg.items()):
        for field in ("revS", "revC", "patS", "patC"):
            if field not in d or d[field] is not None:
                continue
            qe = int(sys.argv[2]) if len(sys.argv) > 2 else 20250331
            val, note = check(sym, qe, field)
            if val is None:
                print("  FAIL %-11s %-5s %s" % (sym, field, note))
            else:
                print("  PASS %-11s %-5s = %-10s %s" % (sym, field, val, note))
                out["%s|%d|%s" % (sym, qe, field)] = {"val": val, "note": note}
    json.dump(out, open("/tmp/screener_gate.json", "w"), indent=1)
    print("\npassed gate: %d" % len(out))


if __name__ == "__main__":
    main()
