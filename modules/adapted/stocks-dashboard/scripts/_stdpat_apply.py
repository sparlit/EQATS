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
"""Apply the 2026-08-10 std-PAT TWO-FILES-ONE-QUANTITY adjudication (stdpat_adjud_verdicts.json).

Dry-run by default; --apply to write. Safety per §2b / §72 apply_staged_heals:
  * guard: every cell's CURRENT value must equal the recorded `was` (tol 0.011) or the run aborts;
  * blast radius: after patching in memory, each of the four twins is diffed against its original
    and the run aborts unless the ONLY changes are the intended cells;
  * idempotent: a cell already at `now` is reported and skipped;
  * journals: pat_defects.json (fund-side, watched by verify_fills_live), stdpat_mirror_heals.json
    (NEW mirror ledger, wired into verify_fills_live LEDGERS), owners_basis_heals.json (the two con
    heals whose _reattr_owners cache still holds the bad value - §71d precedence).
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
V = json.load(open(os.path.join(HERE, "stdpat_adjud_verdicts.json")))
TOL = 0.011
FUND_TWINS = ("docs/sf_fundamentals.json", "scripts/fundamentals.json")
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")


def load(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def dump(rel, obj, pretty=False):
    """Payloads are written with the builders' compact separators so their diffs stay minimal.
    JOURNALS (pat_defects / owners_basis_heals / the mirror ledger) are written PRETTY - they are
    read by humans reviewing provenance, and minifying them turns a 3-line addition into a
    whole-file rewrite that hides what changed."""
    p = os.path.join(ROOT, rel)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if pretty:
            json.dump(obj, fh, indent=1, sort_keys=True)
            fh.write("\n")
        else:
            json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, p)


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= TOL


problems, skipped, plan = [], [], []
orig = {rel: load(rel) for rel in FUND_TWINS + REVOP_TWINS}
work = {rel: copy.deepcopy(orig[rel]) for rel in orig}
expect = {rel: set() for rel in orig}  # (sym, key) allowed to differ


def fund_row(d, sym, qe):
    return next((r for r in d.get(sym, []) if isinstance(r, list) and r and r[0] == int(qe)), None)


def revop_cell(d, rel, sym, qe, create=True):
    """docs payload rows must exist (the scan saw them); the scripts ledger twin is sparser -
    create the row there (only when we will actually write) so the corrected value survives
    rebuilds (fill-only ledger shape)."""
    cell = (d.get(sym) or {}).get(qe)
    if cell is None and create and rel == "scripts/revop_fundamentals.json":
        cell = [None, None, None, None, None, None, 0, None, None]
        d.setdefault(sym, {})[qe] = cell
    if cell is not None and len(cell) < 9:
        cell += [None] * (9 - len(cell))
    return cell


# ---- fund-side std heals (r[1], optional r[2] ann) + mirror follow ----------
for k, e in sorted(V["fund_fix"].items()):
    sym, qe = k.split("|")
    for rel in FUND_TWINS:
        row = fund_row(work[rel], sym, qe)
        if row is None:
            problems.append(f"{rel} {k}: no fund row")
            continue
        if close(row[1], e["now"]) and "ann_now" not in e:
            skipped.append("{} {} already {}".format(rel, k, e["now"]))
            continue
        if not close(row[1], e["was"]) and not close(row[1], e["now"]):
            problems.append("{} {}: GUARD FAILED npStd now {} expected {}".format(rel, k, row[1], e["was"]))
            continue
        if not close(row[1], e["now"]):
            row[1] = e["now"]
            plan.append((rel, k, "npStd", e["was"], e["now"]))
        if "ann_now" in e and row[2] != e["ann_now"]:
            if row[2] != e["ann_was"]:
                problems.append("{} {}: ANN GUARD FAILED now {} expected {}".format(rel, k, row[2], e["ann_was"]))
                continue
            row[2] = e["ann_now"]
            plan.append((rel, k, "annStd", e["ann_was"], e["ann_now"]))
        expect[rel].add((sym, qe))
    # mirror follows the corrected value when it holds the old one (or is empty)
    for rel in REVOP_TWINS:
        cell = revop_cell(work[rel], rel, sym, qe)
        if cell is None:
            continue  # no docs revop row - builders fill later
        cur = cell[4]
        if close(cur, e["now"]):
            continue
        if cur is not None and not close(cur, e["was"]):
            problems.append(
                "{} {}: MIRROR GUARD FAILED patS now {} expected {} or {}".format(rel, k, cur, e["was"], e["now"])
            )
            continue
        cell[4] = e["now"]
        plan.append((rel, k, "patS(follow)", cur, e["now"]))
        expect[rel].add((sym, qe))

# ---- mirror-side resyncs (revop idx4) --------------------------------------
for k, e in sorted(V["mirror_fix"].items()):
    sym, qe = k.split("|")
    # assert the authoritative file already carries the verdict value
    frow = fund_row(work[FUND_TWINS[0]], sym, qe)
    if frow is None or not close(frow[1], e["now"]):
        problems.append("{}: fund does not hold verdict value {} (has {})".format(k, e["now"], frow and frow[1]))
        continue
    for rel in REVOP_TWINS:
        cell = revop_cell(work[rel], rel, sym, qe)
        if cell is None:
            problems.append(f"{rel} {k}: no revop cell")
            continue
        cur = cell[4]
        if close(cur, e["now"]):
            skipped.append("{} {} already {}".format(rel, k, e["now"]))
            continue
        if cur is not None and not close(cur, e["was"]):
            problems.append("{} {}: GUARD FAILED patS now {} expected {}".format(rel, k, cur, e["was"]))
            continue
        cell[4] = e["now"]
        plan.append((rel, k, "patS", cur, e["now"]))
        expect[rel].add((sym, qe))

# ---- con companions (fund r[3] + revop idx5), null allowed ------------------
for k, e in sorted(V["con_fix"].items()):
    sym, qe = k.split("|")
    for rel in FUND_TWINS:
        row = fund_row(work[rel], sym, qe)
        if row is None:
            problems.append(f"{rel} {k}: no fund row (con)")
            continue
        cur = row[3]
        tgt = e["now"]
        if (tgt is None and cur is None) or close(cur, tgt):
            skipped.append(f"{rel} {k} con already {tgt}")
            continue
        if not close(cur, e["was"]):
            problems.append("{} {}: CON GUARD FAILED npCon now {} expected {}".format(rel, k, cur, e["was"]))
            continue
        row[3] = tgt
        if tgt is None:
            row[4] = None
        elif "ann_now" in e:  # revision moved the board-filing date
            if row[4] not in (e["ann_was"], e["ann_now"]):
                problems.append("{} {}: CON ANN GUARD FAILED now {} expected {}".format(rel, k, row[4], e["ann_was"]))
                continue
            row[4] = e["ann_now"]
        plan.append((rel, k, "npCon", e["was"], tgt))
        expect[rel].add((sym, qe))
    for rel in REVOP_TWINS:
        cell = revop_cell(work[rel], rel, sym, qe, create=False)
        if cell is None:
            continue
        cur = cell[5]
        tgt = e["now"]
        # NEVER create a con mirror value where none exists: patC is null for every quarter of a
        # no-sub filer (no consolidated XBRL is ever published), so writing one here would make the
        # healed quarter the ONLY one asserting a consolidated figure. Correct what is there; do
        # not invent. (fund npCon legitimately carries the con=std identity - that is its convention.)
        if cur is None:
            continue
        if (tgt is None and cur is None) or close(cur, tgt):
            continue
        if cur is not None and not close(cur, e["was"]):
            problems.append("{} {}: CON MIRROR GUARD FAILED patC now {} expected {}".format(rel, k, cur, e["was"]))
            continue
        cell[5] = tgt
        plan.append((rel, k, "patC", cur, tgt))
        expect[rel].add((sym, qe))

# ---- blast radius -----------------------------------------------------------
for rel in orig:
    b, a = orig[rel], work[rel]
    diffs = set()
    for sym in set(b) | set(a):
        x, y = b.get(sym), a.get(sym)
        if x == y:
            continue
        if x is None and isinstance(y, dict):  # symbol newly created in the ledger twin
            for q in y:
                diffs.add((sym, q))
            continue
        if isinstance(x, dict) and isinstance(y, dict):
            for q in set(x) | set(y):
                if x.get(q) != y.get(q):
                    diffs.add((sym, q))
        elif isinstance(x, list) and isinstance(y, list):
            for r1, r2 in zip(x, y, strict=False):
                if r1 != r2:
                    diffs.add((sym, str(r1[0])))
            if len(x) != len(y):
                diffs.add((sym, "LEN"))
        else:
            diffs.add((sym, "WHOLE"))
    stray = diffs - expect[rel]
    if stray:
        problems.append(f"{rel}: BLAST RADIUS stray diffs {sorted(stray)[:8]}")

print("planned edits: %d   skipped(already-correct): %d   problems: %d" % (len(plan), len(skipped), len(problems)))
for p in plan:
    print("  EDIT", p)
for s in skipped[:10]:
    print("  SKIP", s)
if len(skipped) > 10:
    print("  ... %d more skips" % (len(skipped) - 10))
for p in problems:
    print("  PROBLEM", p)
if problems:
    sys.exit(1)
if "--apply" not in sys.argv:
    print("DRY RUN - nothing written")
    sys.exit(0)

for rel in orig:
    dump(rel, work[rel])

# ---- journals ---------------------------------------------------------------
pd = load("scripts/pat_defects.json")
for k, e in V["fund_fix"].items():
    sym, qe = k.split("|")
    ent = pd.setdefault(sym, {}).setdefault(qe, {})
    ent.update(
        {
            "stored_pat": e["was"],
            "correct_pat": e["now"],
            "defect": "std-PAT two-files adjudication 2026-08-10",
            "source": e["src"],
        }
    )
for k, e in V["con_fix"].items():
    sym, qe = k.split("|")
    ent = pd.setdefault(sym, {}).setdefault(qe, {})
    ent.update(
        {
            "stored_pat_con": e["was"],
            "correct_pat_con": e["now"],
            "defect": "std-PAT campaign con companion 2026-08-10",
            "source": e["src"],
        }
    )
dump("scripts/pat_defects.json", pd, pretty=True)

mh_path = os.path.join(HERE, "stdpat_mirror_heals.json")
mh = json.load(open(mh_path)) if os.path.exists(mh_path) else {}
mh.setdefault(
    "_README",
    "sf_revop patS (idx4) mirror values fixed/confirmed by the 2026-08-10 std-PAT adjudication (stdpat_adjud_verdicts.json). Watched by verify_fills_live.py; the mirror's authority is sf_fundamentals npStd (runbook §70).",
)
for sec in ("fund_fix", "mirror_fix"):
    for k, e in V[sec].items():
        mh[k] = {"patS": e["now"], "was_mirror": (e["was"] if sec == "mirror_fix" else None), "verdict": sec}
with open(mh_path, "w", encoding="utf-8") as _fh:
    json.dump(mh, _fh, indent=1, sort_keys=True)
    _fh.write("\n")

ob = load("scripts/owners_basis_heals.json")
ob["cells"]["SURAJEST|20240630|patC"] = {
    "period": 30.134,
    "nci": 0.0,
    "owners": 30.13,
    "stored_before": 21.28,
    "note": "fund con poisoned by wrong-year Jun-25 con filing (21.282); true Jun-24 con INDAS_110030 owners==total 30.134, H1 chain 61.9661-31.832 EXACT. _reattr_owners still holds 21.28.",
}
ob["cells"]["DBL|20250930|patC"] = {
    "period": 214.072,
    "nci": 32.579,
    "owners": 181.49,
    "stored_before": 410.47,
    "note": "stored H1 con owners (410.466) as the quarter; Q2 con INDAS_1686466 owners OneD 181.493 (owners+NCI==total closes); H1 owners chain 228.97+181.493 EXACT. _reattr_owners still holds 410.47.",
}
dump("scripts/owners_basis_heals.json", ob, pretty=True)
print("APPLIED %d edits + journals" % len(plan))
