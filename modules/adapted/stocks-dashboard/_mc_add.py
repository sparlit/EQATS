# -*- coding: utf-8 -*-
"""Record Moneycontrol browser-driven reads into scripts/_mc_reads.json.

Same merge-only contract as _vis_add.py (an existing (sym,qe) entry is never overwritten, so
batches are re-runnable). Input on stdin: {SYM: {QE: entry-or-list}}. Each entry carries its own
basis/fin; _apply_reads.py re-anchors every cell against stored sf_fundamentals PAT at apply
time, which is what actually gates the data — a wrong basis assignment here fails the anchor
there instead of writing.

  python -X utf8 scripts/_mc_add.py < batch.json
"""
import os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "_mc_reads.json")


def main():
    blob = json.load(sys.stdin)
    d = json.load(open(P, encoding="utf8")) if os.path.exists(P) else {}
    added = dup = 0
    for sym, cells in blob.items():
        t = d.setdefault(sym, {})
        for qe, c in cells.items():
            if qe in t:
                dup += 1
                continue
            t[qe] = c
            added += 1
    json.dump(d, open(P, "w", encoding="utf8"), indent=1, sort_keys=True)
    total = sum(len(v) for v in d.values())
    print("added %d (%d already present); total %d cells across %d syms"
          % (added, dup, total, len(d)))


if __name__ == "__main__":
    main()
