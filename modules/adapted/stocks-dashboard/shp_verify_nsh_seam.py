# -*- coding: utf-8 -*-
"""ACCEPTANCE GATE for pre-2016 shareholder counts harvested from archived Moneycontrol pages.

The problem: campaign rule 6b wants an exchange document plus >=2 independent sources before a
value is taken — and for Dec-2010..Mar-2016 shareholder counts NONE of that exists. No aggregator
reaches back (Screener's floor is Mar-2017), and BSE's pre-XBRL surface is measured empty
(shpSecSummery_New returns ~505-byte stubs at qtrid 85/80/70). So there is nothing to form a
quorum with, and the honest options are: refuse the data, or find a check that does not need a
second source.

This is that check. Every company in the gap has LATER counts that came from a completely
different source and pipeline (BSE/NSE XBRL, parsed by parse_shp). A shareholder register does not
teleport: it drifts by tens of percent a year, not by orders of magnitude. So the harvested value
is compared against the earliest count we already independently hold, as a compound annual rate.

  PASS    implied CAGR within +/-35%/yr of the anchor  -> continuity holds, accept
  SOFT    within +/-60%/yr                             -> plausible but flag (real events do this:
                                                          IPO-era registers, mergers, bonus issues)
  FAIL    beyond that, or an order-of-magnitude ratio  -> DO NOT MERGE; almost always a parse
                                                          error (wrong column, thousands separator
                                                          eaten, promoter row read as the total)

A FAIL is not proof the source is wrong — but with no second source available, "cannot be
corroborated even by its own future" is where this campaign draws the line.

  python3 -X utf8 scripts/shp_verify_nsh_seam.py --ledger scripts/shp_fill_nsh_pre2016.json.gz \
      --pin origin/main --out nsh_seam_report.json
"""
import os, sys, json, gzip, argparse, subprocess, collections, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
NSH = 6
PASS_CAGR, SOFT_CAGR = 0.35, 0.60
# A time-independent bound is REQUIRED alongside the CAGR test: over 5+ years, compounding dilutes
# even a 10x scale error to about -38%/yr, which the CAGR test alone waves through as SOFT. A real
# register does not multiply or divide by 5 across this era, whatever the span.
RATIO_HI, RATIO_LO = 5.0, 0.2


def load_hist(pin):
    r = subprocess.run(["git", "show", "%s:scripts/shp_history.json" % pin],
                       capture_output=True, cwd=REPO)
    if r.returncode:
        sys.exit("cannot read shp_history.json at %s" % pin)
    return json.loads(r.stdout)


def years_between(a, b):
    return (int(b[:4]) - int(a[:4])) + (int(b[5:7]) - int(a[5:7])) / 12.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True, help='{"counts": {SYM: {QE: int}}}, gz or plain')
    ap.add_argument("--pin", default="origin/main")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    raw = gzip.open(a.ledger, "rb").read() if a.ledger.endswith(".gz") else open(a.ledger, "rb").read()
    led = json.loads(raw)
    counts = led.get("counts", led)
    HIST = load_hist(a.pin)

    rows, tally = [], collections.Counter()
    for sym, qs in counts.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        held = sorted((q, c[NSH]) for q, c in HIST.get(sym, {}).items()
                      if len(c) > NSH and c[NSH])
        for qe, val in sorted(qs.items()):
            try:
                val = int(val)
            except (TypeError, ValueError):
                tally["BAD_VALUE"] += 1
                rows.append({"sym": sym, "qe": qe, "val": val, "verdict": "BAD_VALUE"})
                continue
            already = HIST.get(sym, {}).get(qe)
            if already and len(already) > NSH and already[NSH]:
                tally["ALREADY_HAVE"] += 1
                continue
            # Anchor on the NEAREST independently-sourced count in EITHER direction. Looking only
            # forward left 475 of 575 recent cells unjudged (NO_ANCHOR) — for the newest quarters
            # there IS no later count, but the PRIOR quarter is right there at 99.9% coverage and
            # is a perfectly good continuity reference.
            anchors = sorted(((q, v) for q, v in held if q != qe),
                             key=lambda t: abs(years_between(min(t[0], qe), max(t[0], qe))))
            if not anchors:
                tally["NO_ANCHOR"] += 1
                rows.append({"sym": sym, "qe": qe, "val": val, "verdict": "NO_ANCHOR",
                             "note": "no later independently-sourced count to compare against"})
                continue
            aq, av = anchors[0]
            yrs = abs(years_between(min(aq, qe), max(aq, qe)))
            ratio = (av / val) if val else 0.0
            # CAGR is meaningless across a single quarter: a real 76% move over 3 months
            # annualises to 850%/yr and looks catastrophic. Under a year, judge the RATIO alone.
            cagr = (ratio ** (1.0 / yrs) - 1.0) if (yrs >= 1.0 and ratio > 0) else None
            if ratio <= 0 or ratio > RATIO_HI or ratio < RATIO_LO:
                v = "FAIL"                      # order-of-magnitude: scale/column error
            elif cagr is None:
                v = "PASS"                      # sub-annual span, ratio already inside bounds
            elif abs(cagr) <= PASS_CAGR:
                v = "PASS"
            elif abs(cagr) <= SOFT_CAGR:
                v = "SOFT"
            else:
                v = "FAIL"
            tally[v] += 1
            rows.append({"sym": sym, "qe": qe, "val": val, "anchor_qe": aq, "anchor": av,
                         "years": round(yrs, 2), "ratio": round(ratio, 3),
                         "cagr_pct": (round(100 * cagr, 1) if cagr is not None else None),
                         "verdict": v})

    total = sum(tally[k] for k in ("PASS", "SOFT", "FAIL", "NO_ANCHOR", "BAD_VALUE"))
    print("ledger: %d symbols, %d candidate counts" % (len(counts), total + tally["ALREADY_HAVE"]))
    for k in ("PASS", "SOFT", "FAIL", "NO_ANCHOR", "BAD_VALUE", "ALREADY_HAVE"):
        if tally[k]:
            print("  %-13s %6d%s" % (k, tally[k],
                  "  %5.1f%%" % (100.0 * tally[k] / total) if total and k != "ALREADY_HAVE" else ""))
    fails = [r for r in rows if r["verdict"] == "FAIL"]
    if fails:
        print("\nFAIL — do NOT merge these (worst first):")
        for r in sorted(fails, key=lambda r: -abs(r.get("cagr_pct") or 0))[:20]:
            print("   %-11s %s  harvested=%-9s anchor %s=%-9s  x%-6s %s%%/yr" %
                  (r["sym"], r["qe"], format(r["val"], ","), r.get("anchor_qe"),
                   format(r.get("anchor", 0), ","), r.get("ratio"), r.get("cagr_pct")))
    ok = [r for r in rows if r["verdict"] in ("PASS", "SOFT")]
    if ok:
        cs = [r["cagr_pct"] for r in ok if r.get("cagr_pct") is not None]
        if cs:
            print("\naccepted set: median implied drift %+.1f%%/yr (n=%d) — a real shareholder "
                  "register drifts, it does not jump" % (statistics.median(cs), len(cs)))
    if a.out:
        json.dump({"_meta": {"ledger": a.ledger, "pin": a.pin, "tally": dict(tally)},
                   "rows": rows}, open(a.out, "w", encoding="utf-8"), indent=1)
        print("wrote %s" % a.out)


if __name__ == "__main__":
    main()
