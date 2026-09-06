# -*- coding: utf-8 -*-
"""Apply the HALDER series adjudication (scripts/halder_series_verdicts.json).

Dry-run by default; --apply to write. Same safety envelope as _stdpat_openflag_apply.py (§2b):
  * FILLS guard on ABSENCE — the quarter must not already exist in the payload, or we abort;
  * CORRECTIONS guard on the exact recorded `was` value (tol 0.011) or abort;
  * blast radius: after patching in memory each of the four twins is diffed against its original
    and the run aborts unless the ONLY changes are the intended (sym, quarter) cells;
  * idempotent: a cell already at its target value is reported and skipped, so a re-run is a no-op;
  * journals every cell into TRACKED ledgers that verify_fills_live.py watches:
      named_pat_cell_fills.json  -> fund idx1 (std) + idx3 (con)   [NEW ledger, registered there]
      named_rev_cell_fills.json  -> revop slot 0 (revS) + slot 1 (revC)
      rev_defects.json           -> the Mar-2026 std revenue defect (nested/basis-keyed)
      ann_date_fills.json        -> the two new announce dates

WHAT THIS RUN DOES
  FILL   HALDER 20250630 + 20250930 — the two quarters that existed in no index we ingest. Both
         bases, plus revenue. Anchor chain per cell is in the verdicts file; the short version is
         that each value is PRINTED in the company's own filing, appears in two independent
         filings where a comparative column exists, and closes the H1 and FY26 identities exactly.
  FIX    HALDER 20260331 revS/revC/opS/opC/ebitS/ebitC — every one held the H2 (Oct–Mar) figure.
         §77 healed this scrip's Mar-2026 con PAT for exactly this reason and stopped there; these
         six slots were left carrying the same poison. PAT slots are NOT touched here.

Operating profit is written ONLY for the correction (where the slot already holds a wrong non-null
value and the corrected figure is confirmed twice). It is deliberately left null on the two new
rows — a reconstructed OPM that is wrong is a visible site bug (§2c / fill_std_rev_detres.py).

Run:  python3 scripts/_halder_apply.py [--apply]
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
V = json.load(open(os.path.join(HERE, "halder_series_verdicts.json"), encoding="utf-8"))
TOL = 0.011
SYM = "HALDER"
FUND_TWINS = ("docs/sf_fundamentals.json", "scripts/fundamentals.json")
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")

# sf_revop cell layout (build_revop.py): [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC]
SLOT = {"revS": 0, "revC": 1, "opS": 2, "opC": 3, "patS": 4, "patC": 5, "fin": 6,
        "ebitS": 7, "ebitC": 8}


def load(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def existing_indent(rel, default=1):
    """MATCH THE FILE'S OWN FORMAT. The journals are not uniform: named_rev_cell_fills.json and
    ann_date_fills.json are pretty-printed, rev_defects.json is MINIFIED. Dumping a minified
    ledger with indent=1 rewrites every line — 346 insertions for a one-entry addition, which
    buries the real change and turns a tiny edit into a repo-wide merge surface (the same failure
    mode as sort_keys, §77). Returns None for a minified file, `default` for a pretty one."""
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return default
    with open(p, "rb") as fh:
        head = fh.read(512)
    return default if b"\n" in head.strip() else None


def dump(rel, obj, indent=None):
    """Payloads are minified; pretty JOURNALS stay pretty so they remain human-diffable.
    NEVER sort_keys — json.load preserves file order and re-sorting buries the actual change."""
    p = os.path.join(ROOT, rel)
    had_nl = False
    if indent and os.path.exists(p):
        with open(p, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            had_nl = fh.read(1) == b"\n"
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if indent:
            json.dump(obj, fh, indent=indent)
            if had_nl:
                fh.write("\n")
        else:
            json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, p)


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= TOL


problems, skipped, plan = [], [], []
orig = {rel: load(rel) for rel in FUND_TWINS + REVOP_TWINS}
work = {rel: copy.deepcopy(orig[rel]) for rel in orig}
expect = {rel: set() for rel in orig}

FILLS = V["landed_fills"]
FIX = V["landed_corrections"]

# ---- 1. FILLS: two brand-new quarters, both payload families ------------------------------
for key in sorted(FILLS):
    sym, qe = key.split("|")
    e = FILLS[key]
    if sym != SYM:
        problems.append("%s: unexpected symbol" % key)
        continue
    if int(e["ann"]) <= int(qe):
        problems.append("%s: impossible pair ann <= qe" % key)
        continue

    for rel in FUND_TWINS:
        rows = work[rel].setdefault(sym, [])
        existing = next((r for r in rows if isinstance(r, list) and r and r[0] == int(qe)), None)
        if existing is not None:
            if close(existing[1], e["npStd"]) and close(existing[3], e["npCon"]):
                skipped.append("%s %s fund row already correct" % (rel, key))
            else:
                # A row appearing under us means another writer landed this quarter mid-session.
                # That is a CORRECTION, not a fill — refuse and let a human adjudicate (§2b).
                problems.append("%s %s: fund row ALREADY EXISTS %s — refusing to overwrite a fill"
                                % (rel, key, existing))
            continue
        rows.append([int(qe), e["npStd"], int(e["ann"]), e["npCon"], int(e["ann"])])
        rows.sort(key=lambda r: r[0])
        plan.append((rel, key, "fund NEW ROW", None,
                     [int(qe), e["npStd"], int(e["ann"]), e["npCon"], int(e["ann"])]))
        expect[rel].add((sym, qe))

    for rel in REVOP_TWINS:
        d = work[rel].setdefault(sym, {})
        if qe in d:
            cur = d[qe]
            want = (e["revS"], e["revC"], e["npStd"], e["npCon"])
            got = tuple(cur[i] for i in (SLOT["revS"], SLOT["revC"], SLOT["patS"], SLOT["patC"]))
            if all(close(g, w) for g, w in zip(got, want)):
                skipped.append("%s %s revop row already correct" % (rel, key))
            else:
                # A row appearing under us means another writer landed this quarter mid-session.
                # That is a CORRECTION, not a fill — refuse and let a human adjudicate (§2b).
                problems.append("%s %s: revop row ALREADY EXISTS %s — refusing to overwrite a fill"
                                % (rel, key, cur))
            continue
        # op/ebit deliberately null (see module docstring); fin=0 — HALDER is not a bank/NBFC.
        d[qe] = [e["revS"], e["revC"], None, None, e["npStd"], e["npCon"], 0, None, None]
        plan.append((rel, key, "revop NEW ROW", None, d[qe]))
        expect[rel].add((sym, qe))

# ---- 2. CORRECTION: Mar-2026 H2-as-quarter poison in six revop slots ------------------------
for key in sorted(FIX):
    sym, qe = key.split("|")
    e = FIX[key]
    for rel in REVOP_TWINS:
        cell = (work[rel].get(sym) or {}).get(qe)
        if cell is None:
            # scripts/revop_fundamentals.json legitimately carries a sparser row than docs/ —
            # a missing row there is not an error, there is simply nothing to correct.
            skipped.append("%s %s: no revop row to correct" % (rel, key))
            continue
        while len(cell) < 9:
            cell.append(None)
        for name, want in sorted(e["fix"].items()):
            i = SLOT[name]
            cur, was = cell[i], e["was"][name]
            if close(cur, want):
                skipped.append("%s %s %s already %s" % (rel, key, name, want))
                continue
            if cur is None:
                skipped.append("%s %s %s is null — nothing to correct" % (rel, key, name))
                continue
            if not close(cur, was):
                problems.append("%s %s: GUARD FAILED %s now %s expected %s"
                                % (rel, key, name, cur, was))
                continue
            cell[i] = want
            plan.append((rel, key, "revop %s" % name, cur, want))
            expect[rel].add((sym, qe))

# ---- 3. blast radius ------------------------------------------------------------------------
for rel in orig:
    b, a = orig[rel], work[rel]
    diffs = set()
    for sym in set(b) | set(a):
        x, y = b.get(sym), a.get(sym)
        if x == y:
            continue
        if isinstance(x, dict) and isinstance(y, dict):
            for q in set(x) | set(y):
                if x.get(q) != y.get(q):
                    diffs.add((sym, q))
        elif isinstance(x, list) and isinstance(y, list):
            xr = {r[0]: r for r in x if isinstance(r, list) and r}
            yr = {r[0]: r for r in y if isinstance(r, list) and r}
            for q in set(xr) | set(yr):
                if xr.get(q) != yr.get(q):
                    diffs.add((sym, str(q)))
        elif x is None and isinstance(y, dict):
            for q in y:
                diffs.add((sym, q))
        elif x is None and isinstance(y, list):
            for r in y:
                diffs.add((sym, str(r[0])))
        else:
            diffs.add((sym, "WHOLE"))
    stray = diffs - expect[rel]
    if stray:
        problems.append("%s: BLAST RADIUS stray diffs %s" % (rel, sorted(stray)[:8]))

print("planned edits: %d   skipped(already-correct): %d   problems: %d"
      % (len(plan), len(skipped), len(problems)))
for p in plan:
    print("  EDIT", p)
for s in skipped:
    print("  SKIP", s)
for p in problems:
    print("  PROBLEM", p)
if problems:
    sys.exit(1)
if "--apply" not in sys.argv:
    print("DRY RUN - nothing written")
    sys.exit(0)

for rel in orig:
    dump(rel, work[rel])

# ---- 4. journals ----------------------------------------------------------------------------
APPLIED = "2026-08-10 HALDER series (§77 follow-up)"

pf = os.path.join(HERE, "named_pat_cell_fills.json")
pat_led = json.load(open(pf, encoding="utf-8")) if os.path.exists(pf) else {}
for key, e in FILLS.items():
    pat_led[key] = {"applied": APPLIED, "std": e["npStd"], "con": e["npCon"], "ann": e["ann"],
                    "basis": e["npCon_basis"], "src": e["src"],
                    "evidence": " | ".join(e["anchors"])}
dump("scripts/named_pat_cell_fills.json", pat_led, indent=existing_indent("scripts/named_pat_cell_fills.json"))

rev_led = load("scripts/named_rev_cell_fills.json")
for key, e in FILLS.items():
    rev_led[key] = {"applied": APPLIED, "revS": e["revS"], "revC": e["revC"], "src": e["src"],
                    "evidence": " | ".join(e["anchors"])}
for key, e in FIX.items():
    rev_led[key] = {"applied": APPLIED, "revS": e["fix"]["revS"], "revC": e["fix"]["revC"],
                    "src": "bse-filing-pdf, rendered column read (§62)",
                    "supersedes": {"revS": e["was"]["revS"], "revC": e["was"]["revC"]},
                    "evidence": e["defect"] + " PROOF: " + json.dumps(e["decomposition"])}
dump("scripts/named_rev_cell_fills.json", rev_led, indent=existing_indent("scripts/named_rev_cell_fills.json"))

rd = load("scripts/rev_defects.json")
for key, e in FIX.items():
    sym, qe = key.split("|")
    rd.setdefault(sym, {})[qe] = {
        "bad_rev": e["was"]["revS"], "basis": "std", "correct_rev": e["fix"]["revS"],
        "defect": e["defect"] + " The CON twin (445.17 -> 299.91) and the four operating-profit "
                  "slots carry the identical defect; all six corrected values are journalled in "
                  "named_rev_cell_fills.json and halder_series_verdicts.json.",
        "source": e["document"]}
dump("scripts/rev_defects.json", rd, indent=existing_indent("scripts/rev_defects.json"))

af = load("scripts/ann_date_fills.json")
for key, e in FILLS.items():
    af[key] = {"ann": e["ann"], "src": e["ann_evidence"]}
dump("scripts/ann_date_fills.json", af, indent=existing_indent("scripts/ann_date_fills.json"))

print("APPLIED %d edits + journals" % len(plan))
