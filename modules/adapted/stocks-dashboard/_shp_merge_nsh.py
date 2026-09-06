# -*- coding: utf-8 -*-
"""Fill ONLY the shareholder-count slot from a staged reparse. Percentages are never touched.

Why this exists instead of `_shp_merge_stage.py`: that merger replaces a cell only when the staged
**submission date is strictly newer** (`str(cell[5]) > str(cur[5])`). A `--reparse` re-reads the
SAME filing, so the dates are equal, the cell falls through to `kept`, and an nsh enrichment is
silently discarded — the merge reports success and changes nothing. That is exactly the failure
mode this campaign keeps running into: a tool that looks like it worked.

So this does one surgical thing:
  * where main has no nsh and the staged cell has one -> append/set slot 6, nothing else;
  * where main already has an nsh -> leave it alone (never overwrite a stored count);
  * if ANY of slots 0-5 differ between main and stage -> DO NOT WRITE that cell, report it.
    A reparse of the same filing must reproduce the same percentages. If it doesn't, something
    more interesting than a missing count is going on and it deserves a human, not an overwrite.

Cells present only in the staging file are counted and reported but NOT added — adding new cells
is a different operation with a different evidence bar (campaign rule 6b). Use the normal route.

  python3 -X utf8 scripts/_shp_merge_nsh.py --stage scripts/shp_history_stage.json [--apply]
Dry-run by default: prints exactly what it would do and writes nothing.
"""
import os, sys, json, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "shp_history.json")
PCT = 5          # slots 0..4 are percentages, slot 5 is the submission date
NSH = 6


def load(path):
    for i in range(8):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, PermissionError):
            time.sleep(1 + i)
    return json.load(open(path, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=os.path.join(HERE, "shp_history_stage.json"))
    ap.add_argument("--counts", default="", help='count-only ledger {"counts":{SYM:{QE:int}}}, gz ok')
    ap.add_argument("--accept", default="", help="seam report JSON; merge ONLY its PASS/SOFT rows")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    a = ap.parse_args()

    main_h = load(MAIN)
    if a.counts:
        import gzip as _gz
        raw = _gz.open(a.counts, "rb").read() if a.counts.endswith(".gz") else open(a.counts, "rb").read()
        counts = json.loads(raw).get("counts", {})
        ok = None
        if a.accept:
            rep = json.load(open(a.accept, encoding="utf-8"))
            ok = {(r["sym"], r["qe"]) for r in rep.get("rows", [])
                  if r.get("verdict") in ("PASS", "SOFT")}
            print("acceptance filter: %d PASS/SOFT rows admitted" % len(ok))
        # Shape the count-only ledger into stage form by copying main's OWN percentages, so the
        # drift guard below still runs unchanged and slot 6 is the only thing that can change.
        stage = {}
        for sym, qs in counts.items():
            for qe, n in qs.items():
                if ok is not None and (sym, qe) not in ok:
                    continue
                cur = main_h.get(sym, {}).get(qe)
                if not cur:
                    continue
                cell = list(cur)
                while len(cell) <= NSH:
                    cell.append(None)
                cell[NSH] = int(n)
                stage.setdefault(sym, {})[qe] = cell
    else:
        stage = load(a.stage)
    before = sum(len(v) for k, v in main_h.items() if not k.startswith("_"))
    with_nsh_before = sum(1 for k, v in main_h.items() if not k.startswith("_")
                          for c in v.values() if len(c) > NSH and c[NSH])

    filled = kept = drift = only_stage = no_nsh_in_stage = 0
    drift_rows, per_q = [], {}
    for sym, qs in stage.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        tgt = main_h.get(sym)
        for qe, cell in qs.items():
            if tgt is None or qe not in tgt:
                only_stage += 1
                continue
            cur = tgt[qe]
            snsh = cell[NSH] if len(cell) > NSH else None
            if not snsh:
                no_nsh_in_stage += 1
                continue
            if len(cur) > NSH and cur[NSH]:
                kept += 1
                continue
            same = all(cur[i] == cell[i] for i in range(PCT) if i < len(cur) and i < len(cell))
            if not same:
                drift += 1
                drift_rows.append((sym, qe, cur[:PCT], cell[:PCT]))
                continue
            new = list(cur)
            while len(new) <= NSH:
                new.append(None)
            new[NSH] = snsh
            tgt[qe] = new
            filled += 1
            per_q[qe] = per_q.get(qe, 0) + 1

    after = sum(len(v) for k, v in main_h.items() if not k.startswith("_"))
    with_nsh_after = sum(1 for k, v in main_h.items() if not k.startswith("_")
                         for c in v.values() if len(c) > NSH and c[NSH])
    if after != before:
        sys.exit("ABORT: cell count changed %d -> %d; this tool must never add or remove cells"
                 % (before, after))

    print("cells %d (unchanged, as required)" % before)
    print("nsh coverage  %d -> %d   (+%d)" % (with_nsh_before, with_nsh_after, filled))
    print("  filled            %6d" % filled)
    print("  already had nsh   %6d  (left alone)" % kept)
    print("  stage had no nsh  %6d" % no_nsh_in_stage)
    print("  only in stage     %6d  (NOT added — different evidence bar, rule 6b)" % only_stage)
    print("  PERCENTAGE DRIFT  %6d  (NOT written)" % drift)
    for sym, qe, cur, st in drift_rows[:20]:
        print("     %-11s %s  main=%s  stage=%s" % (sym, qe, cur, st))
    for qe in sorted(per_q):
        print("  +%d at %s" % (per_q[qe], qe))

    if not a.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit these fills.")
        return
    tmp = MAIN + ".tmp.%d" % os.getpid()
    json.dump(main_h, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for i in range(10):
        try:
            os.replace(tmp, MAIN)
            break
        except PermissionError:
            time.sleep(1 + i)
    print("\nWROTE %s  (+%d shareholder counts, 0 percentages touched)" % (MAIN, filled))


if __name__ == "__main__":
    main()
