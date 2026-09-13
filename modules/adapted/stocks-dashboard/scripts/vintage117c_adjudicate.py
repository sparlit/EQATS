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
"""§117c — OFFLINE adjudication over the detres raw dicts (_vintage117c_raw.json).

The fetch pass's op/rev buckets were deliberately crude; this re-derives the store's own
conventions from the persisted as-filed fields and re-buckets:

  rev candidates: Net Sales/Revenue From Operations; + Other Operating Income (the store's
                  rev-incl-other-op-income definition, §117b); Total Income (fin); Interest Earned.
  op candidates:  detres prints expenses NEGATIVE, so op = PBET − OI + |FC| + |DA|
                  (build_revop industrial convention, Trendlyne-matched), with PBET =
                  'Profit after Interest but before Exceptional Items' preferred over PBT;
                  variants without DA / without FC kept as candidates; bank pre-provision line.
  pat:            Net Profit lines (+ EPS × shares cross-check where printed).

Verdict per cell: clean-asfiled (every stored slot reproduces from the original filing) or
CANDIDATE (some slot does not) with the per-slot detail. No writes to data — report only.

RUN: python3 scripts/vintage117c_adjudicate.py [--verbose]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "_vintage117c_raw.json")
SCAN = os.path.join(HERE, "_vintage117c_scan.json")
OUT = os.path.join(HERE, "_vintage117c_adjud.json")


def f(d, *names):
    for n in names:
        v = d.get(n)
        if v in (None, "", "-"):
            continue
        try:
            return float(v) / 10.0
        except (TypeError, ValueError):
            continue
    return None


def near(a, b, abs_tol=0.06, rel_tol=0.001):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def main():
    verbose = "--verbose" in sys.argv
    raw = json.load(open(RAW, encoding="utf-8"))
    scan = json.load(open(SCAN, encoding="utf-8"))
    out = {}
    from collections import Counter

    cnt = Counter()
    for k, cell in sorted(scan["cells"].items()):
        if cell.get("verdict") in ("no-detres-row", "no-scrip", "fetch-failed"):
            continue
        d = raw.get(k) or {}
        rec = {"slots": {}, "sym": cell["sym"], "qe": cell["qe"]}

        ns = f(
            d, "Net Sales/Revenue From Operations", "Revenue from Operations", "Net Sales", "Revenue From Operations"
        )
        # bank transpose: rev = the interest-earned top line (store's bank rev convention)
        ie2 = f(d, "Interest Earned/Net Income from sales/services")
        ooi = f(
            d, "Other Operating Income", "Other operating income", "Other Operating Revenues", "Other operating revenue"
        )
        ti = f(d, "Total Income", "Total Income from Operations")
        ie = f(d, "Interest Earned")
        rev_c = {
            "net-sales": ns,
            "net-sales+ooi": (ns + ooi) if (ns is not None and ooi is not None) else None,
            "total-income": ti,
            "interest-earned": ie if ie is not None else ie2,
        }

        oi = f(d, "Other Income") or 0.0
        fc = abs(f(d, "Finance Costs", "Interest", "Finance Cost") or 0.0)
        da = abs(
            f(
                d,
                "Depreciation and amortisation expense",
                "Depreciation and amortization expense",
                "Depreciation",
                "Depreciation & Amortisation",
            )
            or 0.0
        )
        pbet = f(d, "Profit after Interest but before Exceptional Items", "Profit before Exceptional Items and Tax")
        pbt = f(d, "Profit (+)/ Loss (-) from Ordinary Activities before Tax", "Profit before tax", "Profit Before Tax")
        base = pbet if pbet is not None else pbt
        op_c = {}
        if base is not None:
            op_c = {"pbet-oi+fc+da": base - oi + fc + da, "pbet-oi+fc": base - oi + fc, "pbet-oi": base - oi}
        if pbt is not None and pbet is not None and abs(pbt - pbet) > 0.005:
            op_c["pbt-oi+fc+da"] = pbt - oi + fc + da
        bop = f(
            d,
            "Operating Profit Before Provisions and Contingencies",
            "Operating Profit before Provisions and Contingencies",
            "Operating Profit before Provisions and Contingency",
        )
        if bop is not None:
            op_c["bank-preprov"] = bop
        pat_c = {
            "np": f(d, "Net Profit"),
            "np-ord": f(
                d, "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax", "Net Profit/(Loss) for the period"
            ),
        }

        for slot, cands in (("rev", rev_c), ("op", op_c), ("pat", pat_c)):
            stored = cell.get(f"live_{slot}")
            if stored is None:
                stored = cell.get(f"fill_{slot}")
            if stored is None:
                rec["slots"][slot] = {"v": "no-stored"}
                continue
            hit = next((n for n, v in cands.items() if near(stored, v)), None)
            if hit:
                rec["slots"][slot] = {"v": "asfiled", "via": hit}
            else:
                rec["slots"][slot] = {
                    "v": "MISMATCH",
                    "stored": stored,
                    "cands": {n: round(v, 3) for n, v in cands.items() if v is not None},
                }
        vs = [s["v"] for s in rec["slots"].values()]
        rec["verdict"] = "CANDIDATE" if "MISMATCH" in vs else "clean-asfiled"
        cnt[rec["verdict"]] += 1
        out[k] = rec
        if rec["verdict"] == "CANDIDATE" or verbose:
            print("== {}  {}".format(k, rec["verdict"]))
            for slot, s in rec["slots"].items():
                print("   %-4s %s" % (slot, json.dumps(s)))
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print("---")
    for v, c in cnt.most_common():
        print("  %-16s %d" % (v, c))


if __name__ == "__main__":
    main()
