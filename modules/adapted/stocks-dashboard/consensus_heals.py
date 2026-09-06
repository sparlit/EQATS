# -*- coding: utf-8 -*-
"""Apply a correction ONLY where two independent methods agree on the same value.

Three sources now have an opinion about the audit suspects, and each is fallible in a different way:

  A. triage_suspects.py   deterministic arithmetic (SCALE / CUMULATIVE / FY-IN-QUARTER). Cannot
                          hallucinate, but only fires when an identity fits exactly.
  B. six triage agents    read the same data and reason about it. They found real things the
                          arithmetic missed (Q4-derivation defects, misfiled quarters, std/con
                          basis swaps) -- and they can also be confidently wrong.
  C. adjudicate_suspects  reads the actual FILING. Strongest evidence when it works, but its own
                          reader can return a bad value, which is why it has a plausibility guard.

A single source is not enough to overwrite stored data. This applies a correction only when at
least TWO of the three name the same cell AND their suggested values agree within 2%. Everything
else is written to a review list rather than the dataset -- including every cell where the sources
DISAGREE, which is exactly where a silent auto-fix would do the most damage.

Guards on top of consensus (same as the earlier heals): the cell must still hold the value the
correction was computed against, the replacement must be positive, and it must sit within
[0.2x, 5x] of the company's own neighbouring quarters on the same basis.

  python -X utf8 scripts/fill2020_tools/consensus_heals.py [--apply]
"""
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER_DATA = os.path.join(SCRIPTS, "revop_fundamentals.json")
JOURNAL = os.path.join(SCRIPTS, "consensus_heals.json")
REVIEW = os.path.join(SCRIPTS, "_consensus_review.json")
SLOT = {"revS": 0, "revC": 1}


def agree(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= max(0.05, abs(b) * tol)


def neighbour_median(revop, sym, qe, field):
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
    revop = json.load(open(DOCS))

    # ---- source A: deterministic arithmetic
    A = {}
    for r in json.load(open("/tmp/triage_verdicts.json")):
        if r["bucket"] in ("SCALE", "CUMULATIVE", "FY-IN-QUARTER") and r.get("suggested"):
            A["%s|%s|%s" % (r["sym"], r["qe"], r["field"])] = (r["suggested"], r["bucket"])

    # ---- source B: the triage agents
    B = collections.defaultdict(list)
    for f in sorted(glob.glob("/tmp/triage_out_*.json")):
        for r in json.load(open(f)):
            if r.get("bucket") == "OURS-WRONG" and r.get("suggested_value") is not None:
                B["%s|%s|%s" % (r["sym"], r["qe"], r["field"])].append(
                    (r["suggested_value"], r.get("confidence", "?"), os.path.basename(f)))

    # ---- source C: the filing adjudication
    C = {}
    if os.path.exists("/tmp/adjudicated.json"):
        for k, v in json.load(open("/tmp/adjudicated.json")).items():
            if v.get("verdict") == "OURS-WRONG" and v.get("filing") is not None:
                C[k] = v["filing"]

    keys = set(A) | set(B) | set(C)
    apply_list, review = [], []
    for k in sorted(keys):
        sym, qe, field = k.split("|")
        slot = SLOT[field]
        row = (revop.get(sym) or {}).get(qe)
        cur = row[slot] if row and len(row) > slot else None
        cands = []
        if k in A:
            cands.append(("arithmetic", A[k][0], A[k][1]))
        for v, conf, src in B.get(k, []):
            cands.append(("agent:%s" % conf, v, src))
        if k in C:
            cands.append(("filing", C[k], "adjudicated"))
        srcs = {c[0].split(":")[0] for c in cands}
        if len(srcs) < 2:
            review.append({"cell": k, "current": cur, "candidates": cands,
                           "why": "only one independent source"})
            continue
        # every pair must agree
        vals = [c[1] for c in cands]
        if not all(agree(v, vals[0]) for v in vals):
            review.append({"cell": k, "current": cur, "candidates": cands,
                           "why": "sources DISAGREE on the value"})
            continue
        # NEVER write the MEAN of the candidates -- that invents a figure no source asserts
        # (HYUNDAI: arithmetic 16761.2 + agent 16974 averaged to 16867.60, which is neither).
        # Take the value from the strongest source that has an opinion, in evidence order:
        # the filing itself, then an agent's derived figure, then the pure arithmetic identity.
        rank = {"filing": 0, "agent": 1, "arithmetic": 2}
        new = round(sorted(cands, key=lambda c: rank.get(c[0].split(":")[0], 9))[0][1], 2)
        if cur is None or new <= 0 or agree(new, cur):
            review.append({"cell": k, "current": cur, "candidates": cands,
                           "why": "cell already holds this, or replacement not positive"})
            continue
        med = neighbour_median(revop, sym, int(qe), field)
        if med and not (0.2 * med <= new <= 5 * med):
            review.append({"cell": k, "current": cur, "candidates": cands,
                           "why": "replacement %s outside [0.2x,5x] of neighbour median %.2f"
                                  % (new, med)})
            continue
        apply_list.append((sym, qe, field, cur, new, cands))

    print("cells with an opinion: %d | CONSENSUS (>=2 independent sources agree): %d | review: %d\n"
          % (len(keys), len(apply_list), len(review)))
    for sym, qe, field, cur, new, cands in apply_list[:50]:
        print("  %-12s %-9s %-5s %13.2f -> %-12.2f  [%s]"
              % (sym, qe, field, cur, new, ", ".join(c[0] for c in cands)))
    if dry:
        json.dump(review, open(REVIEW, "w"), indent=1)
        print("\nDRY RUN -- nothing written. review list -> %s" % os.path.basename(REVIEW))
        return

    journal = {}
    for path in (DOCS, LEDGER_DATA):
        d = json.load(open(path))
        n = 0
        for sym, qe, field, cur, new, cands in apply_list:
            row = (d.get(sym) or {}).get(qe)
            if not row or len(row) <= SLOT[field]:
                continue
            if row[SLOT[field]] is None or not agree(row[SLOT[field]], cur, 0.001):
                continue
            row[SLOT[field]] = new
            d[sym][qe] = row
            n += 1
            journal["%s|%s|%s" % (sym, qe, field)] = {
                "was": cur, "now": new,
                "sources": [{"method": c[0], "value": c[1], "detail": c[2]} for c in cands],
                "applied": "2026-08-07 consensus heal"}
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s healed %d" % (os.path.basename(path), n))
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    json.dump(review, open(REVIEW, "w"), indent=1)
    print("journalled %d -> %s | %d held for review" % (len(journal), os.path.basename(JOURNAL),
                                                        len(review)))


if __name__ == "__main__":
    main()
