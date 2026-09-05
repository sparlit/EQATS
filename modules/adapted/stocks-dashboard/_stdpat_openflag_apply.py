# -*- coding: utf-8 -*-
"""Apply the adjudication of the §73 open flags (scripts/stdpat_openflag_verdicts.json).

Dry-run by default; --apply to write. Same safety envelope as _stdpat_apply.py (§2b / §72):
  * guard: every cell's CURRENT value must equal the recorded `was`/`ann_was` (tol 0.011) or abort;
  * blast radius: after patching in memory each of the four twins is diffed against its original
    and the run aborts unless the ONLY changes are the intended cells;
  * idempotent: a cell already at `now` is reported and skipped;
  * journals: pat_defects.json (watched by verify_fills_live on BOTH std idx1 and con idx3),
    stdpat_mirror_heals.json (revop patS idx4), owners_basis_heals.json (outranks the
    _reattr_owners extraction cache in apply_owners_full — §71d), ann_date_fills.json.

RETRACTION: this run also rewrites the §73 record for RPSGVENT|20180630. That heal was made in the
wrong direction, and three artefacts currently PIN the wrong value (stdpat_adjud_verdicts.fund_fix,
pat_defects, stdpat_mirror_heals) — leaving any of them would let a re-run of _stdpat_apply.py or a
verify_fills_live --repair put 2.15 straight back.
"""
import json, os, sys, copy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
V = json.load(open(os.path.join(HERE, "stdpat_openflag_verdicts.json")))
TOL = 0.011
FUND_TWINS = ("docs/sf_fundamentals.json", "scripts/fundamentals.json")
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")


def load(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def dump(rel, obj, indent=None):
    """Payloads are minified; the JOURNALS are pretty-printed so they stay human-diffable.
    NEVER sort_keys here — json.load preserves file order, and re-sorting an existing journal
    rewrites every line and buries the actual change (measured: 260/246 on owners_basis_heals
    for a two-entry addition)."""
    p = os.path.join(ROOT, rel)
    had_nl = False
    if indent and os.path.exists(p):
        with open(p, "rb") as fh:               # match the file's own trailing-newline habit
            fh.seek(-1, os.SEEK_END)
            had_nl = fh.read(1) == b"\n"
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if indent:
            json.dump(obj, fh, indent=indent)   # keep the repo's \uXXXX escaping
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


def fund_row(d, sym, qe):
    return next((r for r in d.get(sym, []) if isinstance(r, list) and r and r[0] == int(qe)), None)


def revop_cell(d, rel, sym, qe):
    """NEVER create a row. Both revop files are DERIVED (scripts/revop_fundamentals.json is
    build_revop's own output, not an input ledger), so a synthesised row is transient noise that
    no rebuild would reproduce — and verify_fills_live --repair only refills rows that exist.
    A quarter with no revop row therefore has no mirror to pin; its authoritative value is
    pinned fund-side in pat_defects.json instead (see `no_mirror` in the verdicts)."""
    cell = (d.get(sym) or {}).get(qe)
    if cell is not None and len(cell) < 9:
        cell += [None] * (9 - len(cell))
    return cell


def patch(section, fund_idx, revop_idx, label):
    """fund_idx = 1 (npStd) or 3 (npCon); revop_idx = 4 (patS) or 5 (patC)."""
    for k, e in sorted(V.get(section, {}).items()):
        sym, qe = k.split("|")
        for rel in FUND_TWINS:
            row = fund_row(work[rel], sym, qe)
            if row is None:
                problems.append("%s %s: no fund row" % (rel, k)); continue
            if close(row[fund_idx], e["now"]):
                skipped.append("%s %s already %s" % (rel, k, e["now"])); continue
            if not close(row[fund_idx], e["was"]):
                problems.append("%s %s: GUARD FAILED %s now %s expected %s"
                                % (rel, k, label, row[fund_idx], e["was"])); continue
            row[fund_idx] = e["now"]
            plan.append((rel, k, label, e["was"], e["now"])); expect[rel].add((sym, qe))
        for rel in REVOP_TWINS:
            cell = revop_cell(work[rel], rel, sym, qe)
            if cell is None:
                continue
            cur = cell[revop_idx]
            if close(cur, e["now"]):
                continue
            if cur is not None and not close(cur, e["was"]):
                problems.append("%s %s: MIRROR GUARD FAILED idx%d now %s expected %s"
                                % (rel, k, revop_idx, cur, e["was"])); continue
            cell[revop_idx] = e["now"]
            plan.append((rel, k, "mirror idx%d" % revop_idx, cur, e["now"])); expect[rel].add((sym, qe))


patch("std_fix", 1, 4, "npStd")
patch("con_fix", 3, 5, "npCon")

# ---- announce dates: fund r[2] (std) only -----------------------------------
for k, e in sorted(V.get("ann_fix", {}).items()):
    sym, qe = k.split("|")
    for rel in FUND_TWINS:
        row = fund_row(work[rel], sym, qe)
        if row is None:
            problems.append("%s %s: no fund row (ann)" % (rel, k)); continue
        if row[2] == e["ann_now"]:
            skipped.append("%s %s ann already %s" % (rel, k, e["ann_now"])); continue
        if row[2] != e["ann_was"]:
            problems.append("%s %s: ANN GUARD FAILED now %s expected %s" % (rel, k, row[2], e["ann_was"])); continue
        if e["ann_now"] <= int(qe):
            problems.append("%s %s: impossible pair ann<=qe" % (rel, k)); continue
        row[2] = e["ann_now"]
        plan.append((rel, k, "annStd", e["ann_was"], e["ann_now"])); expect[rel].add((sym, qe))

# ---- blast radius -----------------------------------------------------------
for rel in orig:
    b, a = orig[rel], work[rel]
    diffs = set()
    for sym in set(b) | set(a):
        x, y = b.get(sym), a.get(sym)
        if x == y:
            continue
        if x is None and isinstance(y, dict):
            for q in y:
                diffs.add((sym, q))
            continue
        if isinstance(x, dict) and isinstance(y, dict):
            for q in set(x) | set(y):
                if x.get(q) != y.get(q):
                    diffs.add((sym, q))
        elif isinstance(x, list) and isinstance(y, list):
            for r1, r2 in zip(x, y):
                if r1 != r2:
                    diffs.add((sym, str(r1[0])))
            if len(x) != len(y):
                diffs.add((sym, "LEN"))
        else:
            diffs.add((sym, "WHOLE"))
    stray = diffs - expect[rel]
    if stray:
        problems.append("%s: BLAST RADIUS stray diffs %s" % (rel, sorted(stray)[:8]))

print("planned edits: %d   skipped(already-correct): %d   problems: %d" % (len(plan), len(skipped), len(problems)))
for p in plan:
    print("  EDIT", p)
for s in skipped:
    print("  SKIP", s)
for p in problems:
    print("  PROBLEM", p)
if problems:
    sys.exit(1)
if "--apply" not in sys.argv:
    print("DRY RUN - nothing written"); sys.exit(0)

for rel in orig:
    dump(rel, work[rel])

# ---- journals ---------------------------------------------------------------
pd = load("scripts/pat_defects.json")
for k, e in V.get("std_fix", {}).items():
    sym, qe = k.split("|")
    ent = pd.setdefault(sym, {}).setdefault(qe, {})
    ent.update({"stored_pat": e["was"], "correct_pat": e["now"],
                "defect": "std-PAT §73 open-flag adjudication 2026-08-10",
                "source": e["src"]})
for k, e in V.get("con_fix", {}).items():
    sym, qe = k.split("|")
    ent = pd.setdefault(sym, {}).setdefault(qe, {})
    ent.update({"stored_pat_con": e["was"], "correct_pat_con": e["now"],
                "defect": "con-PAT §73 open-flag adjudication 2026-08-10",
                "source": e["src"]})
dump("scripts/pat_defects.json", pd, indent=1)

mh = load("scripts/stdpat_mirror_heals.json")
for k, e in V.get("std_fix", {}).items():
    if e.get("no_mirror"):      # no served revop row exists -> nothing for the verifier to check
        mh.pop(k, None)
        continue
    mh[k] = {"patS": e["now"], "was_mirror": e["was"], "verdict": "openflag_std_fix"}
dump("scripts/stdpat_mirror_heals.json", mh, indent=1)

ob = load("scripts/owners_basis_heals.json")
ob["cells"]["HALDER|20260331|patC"] = {
    "period": 19.134, "nci": 2.9486, "owners": 16.19, "stored_before": 36.82,
    "note": "stored the H2 OWNERS figure (29-May-26 XBRL INDAS_1676935 OneD declares Oct-Mar: owners "
            "36.8223). True Q4 = corrected 12-Jun-26 INDAS_1681056 OneD Jan-Mar: owners 161,854,000, "
            "NCI 29,486,000, total 191,340,000. _reattr_owners.json still holds 36.82, so this entry "
            "must outrank it (§71d)."}
ob["cells"]["HALDER|20251231|patC"] = {
    "period": 20.7827, "nci": 0.1459, "owners": 20.64, "stored_before": 20.78,
    "note": "con slot held the TOTAL: the Dec-25 con XBRL INDAS_1625562 carries no attributable tags. "
            "The filing's PDF prints the split (owners 2,063.68 lakh + NCI 14.59 = 2,078.27 total). "
            "Not in _reattr_owners today; pinned so a later ingestion cannot reintroduce the total."}
dump("scripts/owners_basis_heals.json", ob, indent=1)

af = load("scripts/ann_date_fills.json")
for k, e in V.get("ann_fix", {}).items():
    af[k] = {"ann": e["ann_now"], "src": e["match"]}
dump("scripts/ann_date_fills.json", af)

# ---- retract the §73 verdict that this run reverses --------------------------
av_path = "scripts/stdpat_adjud_verdicts.json"
av = load(av_path)
ff = av.get("fund_fix", {})
if "RPSGVENT|20180630" in ff:
    av.setdefault("retracted", {})["RPSGVENT|20180630"] = {
        "was_applied": ff.pop("RPSGVENT|20180630"),
        "retracted_on": "2026-08-10",
        "reason": "WRONG DIRECTION. INDAS_48324_135139_04092019 is the JUN-2019 filing (OneD "
                  "2019-04-01..2019-06-30 = 2.15); NSE double-indexes it under Jun-18 as well, so "
                  "Jun-2018 takes its FourD (2018-04-01..2018-06-30) = 1.65 — the value the store "
                  "already had. Restored to 1.65; see stdpat_openflag_verdicts.json std_fix.",
        "do_not_reapply": True}
av["open_flags_resolved_2026_08_10"] = {
    "verdicts": "scripts/stdpat_openflag_verdicts.json",
    "KOHINOOR 20250331 / 20260331 std": "CONFIRMED CORRECT (genuine exceptional items; both FY identities close on the BSE detres audited annual)",
    "RPSGVENT 20180930 std 58.46": "CONFIRMED CORRECT; the real defect was this campaign's own Jun-2018 heal (retracted above)",
    "METROPOLIS 20180930 std 20.05": "CONFIRMED CORRECT (printed Sep-18 column). Defect was DEC-2018 std 32.40 -> 22.80",
    "HALDER 20260331 con 36.82": "DEFECT -> 16.19 (H2 owners stored as the quarter); companion Dec-2025 con 20.78 -> 20.64 (total stored as owners)",
    "DBL 20251231 con 829.85": "CONFIRMED CORRECT (owners 8,298,518,000 + NCI -408,683,000 == total 7,889,835,000)",
    "Mar-2019 cluster ann dates": "HEALED for GSFC/POLYMED/CARERATING + EMKAY/GREAVESCOT (same fingerprint), measured from the BSE announcement archive",
    "still open": "KALYANI series (Jun-24/Sep-24 std missing, revenue slots unaudited, ISIN resolver guard) — untouched by this run",
}
dump(av_path, av, indent=1)
print("APPLIED %d edits + journals" % len(plan))
