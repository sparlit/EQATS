# -*- coding: utf-8 -*-
"""APPLY the campaign's staged, filing-proven corrections. Dry-run by default; --apply to write.

SCOPE (7 cells, every one arbitrated against the company's own filing):
  GICRE  std PAT  20241231 1623.43 -> 1621.35   | standalone slot held the CONSOLIDATED
                  20250630 2172.77 -> 1752.23   | statement's PRE-ASSOCIATE PAT row
                  20250930 2698.01 -> 2866.79   |
  GICRE  con rev  20240630 12822.55 -> 12886.47 | con slot held a copy of standalone
  AADHARHFC std rev 20230630 533.47 -> 578.01   | revenue slot held the filing's
                    20231231 579.26 -> 658.54   | `Interest income` ROW, not the total

WHY A GUARD-EDIT AND NOT A LEDGER FOR THE PAT CELLS. `scripts/pat_defects.json` is a JOURNAL --
grep shows it is read only by `fill2020_tools/gicre_con_pat.py`, never by CI or a builder. Writing
there records the defect but does not fix the data. The fix therefore follows runbook §2b: guard-
edit BOTH twins, asserting the old value first. The journal is still updated, so provenance survives.

TWINS -- each store has a second copy that must move with it or the next rebuild reintroduces the
old value:
    docs/sf_fundamentals.json  <->  scripts/fundamentals.json      (PAT)
    docs/sf_revop.json         <->  scripts/revop_fundamentals.json (revenue)

SAFETY, all enforced before anything is written:
  * every cell's CURRENT value must equal the recorded guard, or the run aborts. Nothing is forced.
  * BLAST RADIUS: after patching in memory, every file is compared against its original and the run
    aborts unless the ONLY differences are the intended cells.
  * files are rewritten with the same compact separators the builders use, so the diff stays minimal.
  * idempotent: a cell already carrying the corrected value is reported and skipped, not re-written.

AFTER APPLYING (runbook §41 -- journalled is not live): re-run the nightly builders, DIFF, push, and
verify the LIVE per-stock slice ~20 min later, then again after the next nightly.

  python3 -X utf8 scripts/revpat_verify/apply_staged_heals.py          # dry run
  python3 -X utf8 scripts/revpat_verify/apply_staged_heals.py --apply
"""
import os, sys, json, copy

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGED = os.path.join(TREE, "scripts", "revpat_verify", "staged")

FUND_TWINS = ("docs/sf_fundamentals.json", "scripts/fundamentals.json")
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")
TOL = 0.005


def load(rel):
    p = os.path.join(TREE, rel)
    return (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None)


def dump(rel, obj):
    p = os.path.join(TREE, rel)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, p)


def blast_radius(before, after, expect):
    """Return the set of (sym, key) that differ. Used to prove nothing else moved."""
    diffs = set()
    for sym in set(before) | set(after):
        b, a = before.get(sym), after.get(sym)
        if b == a:
            continue
        if isinstance(b, dict) and isinstance(a, dict):
            for k in set(b) | set(a):
                if b.get(k) != a.get(k):
                    diffs.add((sym, str(k)))
        elif isinstance(b, list) and isinstance(a, list):
            for i, (x, y) in enumerate(zip(b, a)):
                if x != y:
                    diffs.add((sym, str(x[0]) if isinstance(x, list) and x else str(i)))
            if len(b) != len(a):
                diffs.add((sym, "LENGTH_CHANGED"))
        else:
            diffs.add((sym, "WHOLE_VALUE"))
    return diffs


def main():
    apply = "--apply" in sys.argv
    pat = json.load(open(os.path.join(STAGED, "pat_defects_staged.json"), encoding="utf-8"))["GICRE"]
    rev = json.load(open(os.path.join(STAGED, "rev_defects_staged.json"), encoding="utf-8"))["AADHARHFC"]
    hdb_p = os.path.join(STAGED, "rev_defects_staged_HDBFS.json")
    hdb = json.load(open(hdb_p, encoding="utf-8"))["HDBFS"] if os.path.exists(hdb_p) else {}
    con = json.load(open(os.path.join(STAGED, "con_copy_reads_staged.json"), encoding="utf-8"))["cells"]
    # optional third packet: further revS/revC corrections, and NULLs where a basis is not filed
    x_p = os.path.join(STAGED, "extra_rev_staged.json")
    extra = json.load(open(x_p, encoding="utf-8")).get("cells", {}) if os.path.exists(x_p) else {}

    plan, problems, skipped = [], [], []

    # ---- PAT: GICRE npStd, in both fundamentals twins -----------------------
    for rel in FUND_TWINS:
        d = load(rel)
        if d is None:
            problems.append("missing twin %s" % rel); continue
        rows = d.get("GICRE") or []
        for q, e in sorted(pat.items()):
            hit = next((r for r in rows if isinstance(r, list) and len(r) >= 5 and r[0] == int(q)), None)
            if hit is None:
                problems.append("%s GICRE %s: no row" % (rel, q)); continue
            cur = hit[1]
            if cur is not None and abs(cur - e["correct_pat"]) <= TOL:
                skipped.append("%s GICRE %s already corrected" % (rel, q)); continue
            if cur is None or abs(cur - e["stored_pat"]) > TOL:
                problems.append("%s GICRE %s: GUARD FAILED (now %s, expected %s)"
                                % (rel, q, cur, e["stored_pat"])); continue
            plan.append((rel, "GICRE", q, "npStd", cur, e["correct_pat"]))

    # ---- revenue: AADHARHFC revS + GICRE revC, in both revop twins ----------
    for rel in REVOP_TWINS:
        d = load(rel)
        if d is None:
            problems.append("missing twin %s" % rel); continue
        for sym, q, idx, guard, want, lbl in (
                [("AADHARHFC", q, 0, e["bad_rev"], e["correct_rev"], "revS") for q, e in rev.items()] +
                [("HDBFS", q, 0, e["bad_rev"], e["correct_rev"], "revS") for q, e in hdb.items()] +
                [(k.split("|")[0], k.split("|")[1], 1, v["was"], v["value"], "revC")
                 for k, v in con.items()] +
                [(k.split("|")[0], k.split("|")[1], 0 if k.split("|")[2] == "revS" else 1,
                  v["was"], v["value"], k.split("|")[2]) for k, v in extra.items()]):
            row = (d.get(sym) or {}).get(q)
            if not row:
                problems.append("%s %s %s: no row" % (rel, sym, q)); continue
            cur = row[idx] if len(row) > idx else None
            if want is None:                      # NULL: removing a value that was never filed
                if cur is None:
                    skipped.append("%s %s %s %s already null" % (rel, sym, q, lbl)); continue
                if abs(cur - guard) > TOL:
                    problems.append("%s %s %s %s: GUARD FAILED for NULL (now %s, expected %s)"
                                    % (rel, sym, q, lbl, cur, guard)); continue
                plan.append((rel, sym, q, lbl, cur, None)); continue
            if cur is not None and abs(cur - want) <= TOL:
                skipped.append("%s %s %s %s already corrected" % (rel, sym, q, lbl)); continue
            if cur is None or abs(cur - guard) > TOL:
                problems.append("%s %s %s %s: GUARD FAILED (now %s, expected %s)"
                                % (rel, sym, q, lbl, cur, guard)); continue
            plan.append((rel, sym, q, lbl, cur, want))

    print("PLANNED WRITES: %d" % len(plan))
    for rel, sym, q, fld, a_, b_ in plan:
        print("   %-32s %-10s %s %-5s %12s -> %s" % (os.path.basename(rel), sym, q, fld, a_,
                                                      "NULL (basis not filed)" if b_ is None else b_))
    if skipped:
        print("\nALREADY CORRECT (idempotent skip): %d" % len(skipped))
        for s in skipped[:8]:
            print("   %s" % s)
    if problems:
        print("\n*** ABORTING — %d problem(s); nothing written ***" % len(problems))
        for p_ in problems:
            print("   %s" % p_)
        sys.exit(1)
    if not apply:
        print("\nDRY RUN — re-run with --apply to write."); return
    if not plan:
        print("\nnothing to do."); return

    # ---- write, with a blast-radius proof per file --------------------------
    for rel in FUND_TWINS + REVOP_TWINS:
        mine = [p for p in plan if p[0] == rel]
        if not mine:
            continue
        d = load(rel)
        before = copy.deepcopy(d)
        expect = set()
        for _rel, sym, q, fld, _a, b_ in mine:
            if fld == "npStd":
                for r in d[sym]:
                    if isinstance(r, list) and len(r) >= 5 and r[0] == int(q):
                        r[1] = b_
            else:
                d[sym][q][0 if fld == "revS" else 1] = b_
            expect.add((sym, q))
        diffs = blast_radius(before, d, expect)
        if diffs != expect:
            print("*** ABORT %s: blast radius %s != intended %s ***" % (rel, sorted(diffs), sorted(expect)))
            sys.exit(1)
        dump(rel, d)
        print("wrote %-34s %d cell(s), blast radius verified == intended" % (rel, len(mine)))

    # ---- journal provenance into the tracked ledgers ------------------------
    pd_p = "scripts/pat_defects.json"
    pd = load(pd_p) or {}
    pd.setdefault("GICRE", {})
    for q, e in pat.items():
        pd["GICRE"][q] = {"stored_pat": e["stored_pat"], "correct_pat": e["correct_pat"],
                          "defect": e["defect"], "source": e.get("source"),
                          "quorum": e.get("quorum")}
    with open(os.path.join(TREE, pd_p), "w", encoding="utf-8") as fh:
        json.dump(pd, fh, indent=1)
    rd_p = "scripts/rev_defects.json"
    rd = load(rd_p) or {}
    for sym, cells in (("AADHARHFC", rev), ("HDBFS", hdb)):
        if not cells:
            continue
        rd.setdefault(sym, {})
        for q, e in cells.items():
            rd[sym][q] = {"bad_rev": e["bad_rev"], "correct_rev": e["correct_rev"],
                          "basis": "std", "defect": e["defect"], "source": e.get("source")}
    with open(os.path.join(TREE, rd_p), "w", encoding="utf-8") as fh:
        json.dump(rd, fh, indent=1)
    print("journalled provenance -> %s, %s" % (pd_p, rd_p))
    print("\nAPPLIED. Next (runbook §41): rebuild derived outputs, DIFF, push, verify LIVE ~20 min,"
          " and again after the next nightly.")


if __name__ == "__main__":
    main()
