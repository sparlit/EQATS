# -*- coding: utf-8 -*-
"""Adjudicate the ISOLATED-DIFF suspects against the FILING — who is right, us or screener?

User, 2026-08-07: *"filling empty cells has to be done after every single cell is done comparing
with screener and solving them"*. Correct order. triage_suspects.py already resolved everything
decidable by arithmetic (SCALE / CUMULATIVE / FY-IN-QUARTER) and separated the RUNs, which are not
per-cell defects. What is left is 661 cells where our value and screener's simply differ and no
identity explains it. For those the tie-breaker is the primary source.

METHOD: read the company's own filing for that quarter and basis with the §61/§62 reader --
geometric column addressing, anchored on our STORED PAT (which is an independent quantity from the
revenue being adjudicated). Then compare what the filing says against both claims:

    filing == ours       -> OURS-CORRECT. screener differs for its own reasons (restatement,
                            a definitional row choice). Nothing to fix; record it so the cell is
                            never re-flagged.
    filing == screener   -> OURS-WRONG, and now we have the exact figure, not a rounded one.
    filing == neither    -> UNRESOLVED. Report it; do NOT invent a third value.
    no filing read       -> NEEDS-SOURCE (transport, image-only, or no anchor).

Read-only: writes /tmp/adjudicated.json only. Corrections are applied by a separate reviewed step,
so there is a single writer to the dataset.

  python -X utf8 scripts/fill2020_tools/adjudicate_suspects.py [--limit N] [--resume]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
import build_targets as BT                                        # noqa: E402
import universal_read as U                                        # noqa: E402

REVOP = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
SLOT = {"revS": 0, "revC": 1}


def neighbour_median(sym, qe, field):
    """Median stored revenue on THIS basis from the 8 nearest quarters -- the plausibility scale."""
    slot = SLOT[field]
    have = []
    for q, row in (REVOP.get(sym) or {}).items():
        if int(q) == qe or not row or len(row) <= slot or row[slot] is None or row[slot] <= 0:
            continue
        have.append((abs(int(q) - qe), row[slot]))
    vals = sorted(v for _d, v in sorted(have)[:8])
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0

OUT = "/tmp/adjudicated.json"


def close(a, b, tol=0.015, floor=1.0):
    return a is not None and b is not None and abs(a - b) <= max(floor, abs(b) * tol)


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    verdicts = json.load(open("/tmp/triage_verdicts.json"))
    todo = [r for r in verdicts if r["bucket"] == "ISOLATED-DIFF"]
    scrips = BT.scrip_map()

    done = {}
    if "--resume" in sys.argv and os.path.exists(OUT):
        done = json.load(open(OUT))

    n = 0
    for r in todo:
        key = "%s|%d|%s" % (r["sym"], r["qe"], r["field"])
        # Skip anything already decided. NEEDS-SOURCE is only retried with --retry-source: those
        # cells failed on transport or had no readable statement, and re-attempting them every run
        # consumed the whole --limit before reaching a single NEW cell (74 -> 83 in one chunk).
        if key in done and (done[key]["verdict"] != "NEEDS-SOURCE" or "--retry-source" not in sys.argv):
            continue
        if n >= limit:
            break
        n += 1
        scrip = scrips.get(r["sym"].upper())
        if not scrip:
            done[key] = {"verdict": "NEEDS-SOURCE", "why": "no BSE scrip"}
            json.dump(done, open(OUT, "w"), indent=1)
            continue
        try:
            res = U.read_cell(r["sym"], int(r["qe"]), r["field"], scrip, None)
        except Exception as e:
            done[key] = {"verdict": "NEEDS-SOURCE", "why": repr(e)[:70]}
            json.dump(done, open(OUT, "w"), indent=1)
            continue
        if res.get("state") != "FILLED-EXACT":
            done[key] = {"verdict": "NEEDS-SOURCE", "why": res.get("state"),
                         "trace": res.get("trace")}
        else:
            filing = res["value"]
            med = neighbour_median(r["sym"], int(r["qe"]), r["field"])
            # A read that is orders of magnitude away from this company's own neighbouring quarters
            # is a BAD READ (wrong row, wrong scale), not evidence about the cell. Without this,
            # ACC Dec-2024 came back at 657,562 against a ~5,900 series, and ACUTAAS "agreed" with
            # our 24,359.2 when both were lakh against screener's 244 crore -- a false OURS-CORRECT.
            if med and not (0.2 * med <= filing <= 5 * med):
                ours_ok = 0.2 * med <= r["ours"] <= 5 * med
                scr_ok = 0.2 * med <= r["screener"] <= 5 * med
                done[key] = {"verdict": "READ-SUSPECT", "filing": filing, "ours": r["ours"],
                             "screener": r["screener"], "neighbour_median": round(med, 2),
                             "ours_in_band": ours_ok, "screener_in_band": scr_ok,
                             "why": "filing read %.2f is outside [0.2x,5x] of the neighbour median "
                                    "%.2f -- treating the READ as unreliable" % (filing, med)}
                json.dump(done, open(OUT, "w"), indent=1)
                continue
            if close(filing, r["ours"]):
                v = "OURS-CORRECT"
            elif close(filing, r["screener"]):
                v = "OURS-WRONG"
            else:
                v = "UNRESOLVED"
            done[key] = {"verdict": v, "filing": filing, "ours": r["ours"],
                         "screener": r["screener"], "evidence": res.get("evidence")}
            print("  %-14s %-28s filing=%-12s ours=%-12s screener=%s"
                  % (v, key, filing, r["ours"], r["screener"]))
        json.dump(done, open(OUT, "w"), indent=1)

    c = collections.Counter(v["verdict"] for v in done.values())
    print("\nadjudicated %d of %d ISOLATED-DIFF" % (len(done), len(todo)))
    for k, v in c.most_common():
        print("   %-14s %d" % (k, v))
    print("-> %s" % OUT)


if __name__ == "__main__":
    main()
