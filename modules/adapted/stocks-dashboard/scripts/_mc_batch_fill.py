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
"""Fill missing standalone-revenue cells for a symbol list from Moneycontrol's deep std feed.

For the 2011-trough batch (pre-XBRL 2008-2011 quarters of still-filing N500 members). MC's
`type_format=quarterly` standalone feed reaches ~1997 and serves the AS-FILED vintage (§108),
so it fills the pre-XBRL gap the campaign's XBRL routes could not.

WHY convention-matching (the part the applier does NOT gate). _apply_reads re-anchors on PAT only,
so a wrong revenue LINE would still be written. Our stored revStd convention = "total income from
operations" = MC rev_total for industrials, but = Interest Earned (rev_ops) for banks and some
lenders. So per symbol we DETERMINE the convention by matching MC against the symbol's OWN existing
stored revStd, and only fill where that convention is established (or, with no overlap, default to
rev_total and mark low-confidence for review). Every fill also carries pat_seen = MC pat_total, so
the apply-time anchor still gates the vintage.

Run:  python -X utf8 scripts/_mc_batch_fill.py --cells <batch60_cells.json> [--emit <out.json>]
      then pipe <out.json> to _mc_add.py and apply.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "agg_tools"))
import agg_sources as A

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def close(a, b, tol_abs=0.5, tol_pct=0.01):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol_abs, tol_pct * max(abs(a), abs(b)))


def main():
    argv = sys.argv
    cells_path = argv[argv.index("--cells") + 1]
    out_path = argv[argv.index("--emit") + 1] if "--emit" in argv else os.path.join(HERE, "_mc_batch_emit.json")
    batch = json.load(open(cells_path))
    want = batch["cells"]  # {sym: [qe,...]}
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    rev = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))

    emit = {}
    report = {
        "symbols": len(want),
        "conv_total": 0,
        "conv_ops": 0,
        "conv_default": 0,
        "no_mc": [],
        "filled": 0,
        "per_sym": {},
    }
    for sym in sorted(want):
        {r[0]: r for r in fund.get(sym, [])}
        srev = rev.get(sym) or {}
        finflag = 0
        for r in srev.values():  # inherit the symbol's fin marker if any row has it
            if len(r) > 6 and r[6]:
                finflag = 1
                break
        q, note = A.mc_quarters(sym, con=False)
        if not q:
            report["no_mc"].append((sym, note))
            continue
        # determine convention: vote across quarters where stored revStd exists AND MC has the qe
        vt = vo = 0
        for qe_s, rr in srev.items():
            stored = rr[0]
            mc = q.get(int(qe_s))
            if stored is None or not mc:
                continue
            if close(stored, mc.get("rev_total")):
                vt += 1
            if close(stored, mc.get("rev_ops")):
                vo += 1
        if vt == 0 and vo == 0:
            conv, ckey = "default_rev_total", "rev_total"
            report["conv_default"] += 1
        elif vo > vt:
            conv, ckey = "rev_ops", "rev_ops"
            report["conv_ops"] += 1
        else:
            conv, ckey = "rev_total", "rev_total"
            report["conv_total"] += 1
        # stage missing cells
        got = []
        for qe in want[sym]:
            mc = q.get(int(qe))
            if not mc or mc.get("pat_total") is None or mc.get(ckey) is None:
                continue
            emit.setdefault(sym, {})[str(qe)] = {
                "basis": "std",
                "rev": mc[ckey],
                "pat_seen": mc["pat_total"],
                "fin": finflag,
                "src": "moneycontrol std {}={} pat={} (deep feed, as-filed; conv={}{}) [batch60 2026-08-24]".format(
                    ckey, mc[ckey], mc["pat_total"], conv, "" if conv != "default_rev_total" else " NO-OVERLAP-DEFAULT"
                ),
            }
            got.append(qe)
        report["filled"] += len(got)
        report["per_sym"][sym] = {"conv": conv, "staged": len(got), "of_missing": len(want[sym])}
    json.dump(emit, open(out_path, "w"), indent=1, sort_keys=True)
    print("staged %d cells across %d syms -> %s" % (report["filled"], len(emit), out_path))
    print(
        "convention: rev_total %d | rev_ops(bank) %d | no-overlap-default %d | no MC %d"
        % (report["conv_total"], report["conv_ops"], report["conv_default"], len(report["no_mc"]))
    )
    if report["no_mc"]:
        print("  no MC match:", ", ".join(s for s, _ in report["no_mc"]))
    defaults = [s for s, v in report["per_sym"].items() if v["conv"] == "default_rev_total" and v["staged"]]
    if defaults:
        print("  LOW-CONFIDENCE (no existing revStd to confirm convention):", ", ".join(defaults))
    json.dump(report, open(os.path.join(HERE, "_mc_batch_report.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
