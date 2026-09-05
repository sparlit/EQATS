# -*- coding: utf-8 -*-
"""WHOLE-HISTORY revenue fill from Moneycontrol — 2026 back to 2002, ONE client  (2026-08-11)

WHY ONE PASS AND ONE CLIENT. A single request per (symbol, basis) returns that company's ENTIRE
quarterly history, so filling the whole store is a loop over ~3,600 SYMBOLS, not over the ~46,000
empty cells. Splitting that across sessions buys no speed and costs contention on a shared endpoint
— which is how you lose it for everyone. The user consolidated the work here for that reason.

Everything below is the accumulated discipline of three sessions; none of it is optional.

★ limit IS A SILENT CAP AND `count` MIRRORS IT (memory: feedback-endpoint-caps-are-silent).
  limit=60 -> 60 rows / count:60 / oldest Sep-2011;  limit=200 -> 77 rows / Jun-2007 (DLF con).
  Quoting "60 quarters" as the site's reach is quoting your own parameter. We use 400, and the disk
  cache key INCLUDES the limit — it did not at first, so a cached short body was silently reused.

★ THERE IS NO ONE REVENUE ROW. "Net Sales/Income from operations" is only the premium leg for
  insurers (GICRE con reproduces 0/18 of our quarters on it, 16/18 on "Total Income From
  Operations"; NIACL 1/22 vs 18/22). Try every candidate row and keep whichever REPRODUCES our
  stored values. That is also what makes bank layouts ("Interest Earned") safe.

★ THE GATE — the series must be right WHERE WE READ, not everywhere.
  Demanding zero disagreements across 40+ quarters refuses a cell with a dozen exact local anchors
  because of one miss years away, and those distant misses are usually OUR bad cells. So per target
  quarter: NO disagreement within ±6 quarters, ≥3 anchors inside that window, and a global
  disagreement rate under 15%.

★ MAGNITUDE IS NOT PROVEN BY AN ANCHOR (runbook §83, HINDALCO 2018-12: a fused digit made 33,213
  read as 332,131 — syntactically valid, correct column, wrong by 10x). Every value written here is
  also banded against the NEAREST SIX same-basis stored quarters, never the series median: a
  company whose revenue doubles across the window makes a global median hide an order of magnitude.

★ SYMBOL RESOLUTION (§49 one layer up): MC codes are opaque and a guessed one returns a plausible
  page for the WRONG company. Resolve via MC's own search, verify the NSE symbol in the row, and
  prefer the `sc_id` FIELD — the code at the end of link_src answers the feed 0 rows with HTTP 200
  (SPICEJET SJ01 -> 0 rows vs sc_id ML04 -> 73).

Fill-only, newest quarters first. Ledger scripts/mc_history_fills.json (tracked).
Run: python -X utf8 scripts/fill2020_tools/mc_fill_all_history.py [--limit-syms N] [--min-qe 20021231] [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)

import mc_quarterly_fetch as MC                                   # noqa: E402

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "mc_history_fills.json")
SKIPS = os.path.join(HERE, "_mc_history_skips.json")

NEIGHBOURS = 6                    # §83 band: nearest N same-basis stored quarters
BAND_LO, BAND_HI = 0.2, 5.0


def band_ok(ours, qe, v):
    """§83: order-of-magnitude guard against the NEAREST quarters, never the series median."""
    near = sorted(ours.items(), key=lambda kv: abs(kv[0] - qe))[:NEIGHBOURS]
    vals = sorted(x for _, x in near if x > 0)
    if not vals:
        return True, None
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
    if med <= 0:
        return True, None
    r = v / med
    return (BAND_LO <= r <= BAND_HI), round(r, 3)


def main():
    argv = sys.argv
    apply_it = "--apply" in argv
    lim_syms = int(argv[argv.index("--limit-syms") + 1]) if "--limit-syms" in argv else None
    min_qe = int(argv[argv.index("--min-qe") + 1]) if "--min-qe" in argv else 20021231

    revop = json.load(open(REVOP))
    ledger = json.load(open(LEDGER))
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    codes = json.load(open(MC.CODES)) if os.path.exists(MC.CODES) else {}

    # gateable universe: a basis needs >=6 stored quarters for the gate to mean anything
    work = []
    for sym, qmap in revop.items():
        for basis in ("std", "con"):
            slot = MC.SLOT[basis]
            have = sum(1 for r in qmap.values() if len(r) > slot and r[slot] is not None)
            gaps = [int(q) for q, r in qmap.items()
                    if len(r) > slot and r[slot] is None and int(q) >= min_qe]
            if have >= 6 and gaps:
                work.append((sym, basis, sorted(gaps, reverse=True)))   # NEWEST FIRST
    work.sort(key=lambda t: (-len(t[2]), t[0]))
    if lim_syms:
        work = work[:lim_syms]
    print("gateable (symbol,basis) pairs with open cells: %d | open cells in scope: %d"
          % (len(work), sum(len(g) for _, _, g in work)), flush=True)

    read = 0
    retry = set()
    for n, (sym, basis, gaps) in enumerate(work, 1):
        pre = sym in codes
        code = MC.resolve_code(sym, codes)
        if not pre:
            MC._jitter(0.4, 0.9)
        if not code:
            skips["%s|%s" % (sym, basis)] = "no verified moneycontrol code"
            continue
        ours = {int(q): r[MC.SLOT[basis]] for q, r in (revop.get(sym) or {}).items()
                if len(r) > MC.SLOT[basis] and r[MC.SLOT[basis]] is not None}
        mc, label = MC.series(code, basis, limit=400, ours=ours)
        MC._jitter()
        if not mc:
            # ⚠️ RETRYABLE, NOT A VERDICT (§55a). An empty body is a run-time condition — rate
            # limiting, a transient 5xx, or this process competing with another client — and
            # writing it into skips as "no data" turns a momentary failure into a permanent
            # not-covered verdict. Measured: AXISBANK con recorded "empty" here while a direct
            # fetch of the same sc_id/limit returns 33 rows. Keep these in a separate retry pool.
            retry.add((sym, basis))
            skips["%s|%s" % (sym, basis)] = "RETRYABLE empty %s series (run-time, not evidence)" % basis
            continue
        got = 0
        for qe in gaps:
            key = "%s|%d|%s" % (sym, qe, basis)
            if key in fills or qe not in mc:
                continue
            v = mc[qe]
            if v <= 0:
                continue
            ok, match, bad, why = MC.gate(mc, ours, target=qe)
            if not ok:
                skips[key] = "GATE(%s): %s" % (label, why)
                continue
            bok, ratio = band_ok(ours, qe, v)
            if not bok:
                skips[key] = ("§83 band: %.2f is %sx the nearest-6 median — magnitude not proven "
                              "by the anchor" % (v, ratio))
                continue
            fills[key] = {"rev": round(v, 2), "row_label": label, "sc_id": code,
                          "type_format": MC.FMT[basis], "neighbour_ratio": ratio,
                          "gate": "%d anchors, %d distant disagreements, none within ±6 quarters"
                                  % (len(match), len(bad)),
                          "src": "moneycontrol appfeeds quarterly_results_responsive limit=400"}
            read += 1
            got += 1
        if got:
            print("%-13s %-3s +%-3d cells (%s, %d anchors)" % (sym, basis, got, label, len(ours)),
                  flush=True)
        if n % 25 == 0:
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
            print("  [%d/%d pairs] %d cells read" % (n, len(work), read), flush=True)

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
    json.dump(sorted("%s|%s" % t for t in retry), open(os.path.join(HERE, "_mc_retry.json"), "w"), indent=1)
    print("\nREAD %d cells (%d ledgered)" % (read, len(fills)))
    print("RETRYABLE empty-series pairs (re-run to resolve, NOT 'no data'): %d" % len(retry))
    if not apply_it:
        print("(dry run — ledgers written, data files untouched. Re-run with --apply)")
        return

    applied = 0
    held = 0
    for key, v in sorted(fills.items()):
        # HELD by the con-fallback screen (mc_con_fallback_screen.py): Moneycontrol's consolidated
        # table repeats the STANDALONE figure in quarters with no consolidated filing.
        if v.get("held"):
            held += 1
            continue
        sym, qe_s, basis = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None or row[MC.SLOT[basis]] is not None:
            continue
        row[MC.SLOT[basis]] = v["rev"]
        applied += 1
        lr = ledger.setdefault(sym, {}).get(qe_s)
        if lr is None:
            ledger[sym][qe_s] = list(row)
        elif lr[MC.SLOT[basis]] is None:
            lr[MC.SLOT[basis]] = v["rev"]
    json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
    print("APPLIED %d cells; HELD %d by the con-fallback screen" % (applied, held))


if __name__ == "__main__":
    main()
