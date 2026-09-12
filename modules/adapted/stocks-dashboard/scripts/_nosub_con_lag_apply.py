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
"""Apply the 2026-08-10 nosub_con_lag adjudication (scripts/nosub_con_lag_verdicts.json, runbook §73a).

Dry-run by default; --apply to write. Safety per §2b / §73's _stdpat_apply:
  * GUARD: every slot's CURRENT value must equal the recorded `was` (tol 0.011) or the run aborts;
  * BLAST RADIUS: after patching in memory, each touched file is diffed against its original and
    the run aborts unless the ONLY differences are the intended (sym, qe, slot) cells;
  * IDEMPOTENT: a slot already at `now` is reported and skipped, not re-guarded;
  * TWINS: fund heals go to BOTH docs/sf_fundamentals.json and scripts/fundamentals.json; mirror
    heals go to docs/sf_revop.json and, only where the row already exists, scripts/revop_fundamentals.json;
  * NEVER CREATES a slot: §73a - do not invent a patC where the mirror has none (build_revop records
    only what a filing prints, so a fabricated con figure would be the sole cell asserting one).
  * JOURNAL: pat_defects.json (nested {SYM:{QE:{...}}}, watched by verify_fills_live at fund idx1/idx3),
    merged into any existing entries rather than overwriting them.

Run:  python3 scripts/_nosub_con_lag_apply.py [--apply]
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
V = json.load(open(os.path.join(HERE, "nosub_con_lag_verdicts.json"), encoding="utf-8"))
TOL = 0.011

FUND_TWINS = ("docs/sf_fundamentals.json", "scripts/fundamentals.json")
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")
FUND_SLOT = {"std": 1, "con": 3}
REVOP_SLOT = {"patS": 4, "patC": 5}


def load(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def dump(rel, obj, pretty=False):
    """Payloads keep the builders' compact separators so diffs stay minimal; JOURNALS are pretty,
    because a human reviews their provenance and minifying turns an addition into a whole-file rewrite.

    ★ NEVER sort_keys on a journal. These files are appended to by many campaigns and are NOT in
    sorted order; re-sorting them rewrites hundreds of untouched lines and buries the few that
    changed (it also silently dropped a top-level key once). json.load preserves file order, so
    dumping without sort_keys leaves every entry this run did not touch byte-identical."""
    p = os.path.join(ROOT, rel)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if pretty:
            json.dump(obj, fh, indent=1)
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


# ---------------- fund-side heals (the 17 screen cells + the companions) --------------------
entries = []
for k, e in sorted(V["cells"].items()):
    if e.get("fix"):
        entries.append((k, e["fix"], "screen"))
for k, e in sorted(V["companions"].items()):
    entries.append((k, e["fix"], "companion"))

for k, fix, kind in entries:
    sym, qe = k.split("|")
    for slot_name, (was, now) in sorted(fix.items()):
        idx = FUND_SLOT[slot_name]
        for rel in FUND_TWINS:
            row = fund_row(work[rel], sym, qe)
            if row is None:
                problems.append(f"{rel} {k}: no fund row")
                continue
            cur = row[idx] if len(row) > idx else None
            if close(cur, now):
                skipped.append(f"{rel} {k} {slot_name} already {now}")
                continue
            if not close(cur, was):
                problems.append(f"{rel} {k} {slot_name}: GUARD FAILED - current {cur}, expected was={was}")
                continue
            row[idx] = now
            expect[rel].add((sym, int(qe)))
            plan.append("%-32s %-11s %s %-4s %12s -> %-8s [%s]" % (rel, sym, qe, slot_name, was, now, kind))

# ---------------- mirror-side heals (sf_revop patS/patC) ------------------------------------
for k, fix in sorted(V["mirror"].items()):
    sym, qe = k.split("|")
    for slot_name, (was, now) in sorted(fix.items()):
        idx = REVOP_SLOT[slot_name]
        for rel in REVOP_TWINS:
            cell = (work[rel].get(sym) or {}).get(qe)
            if cell is None:
                # NOT an error: the scripts-side ledger is sparser. Never create a row/slot here.
                skipped.append(f"{rel} {k} {slot_name}: no mirror row (not created - §73a)")
                continue
            cur = cell[idx] if len(cell) > idx else None
            if close(cur, now):
                skipped.append(f"{rel} {k} {slot_name} already {now}")
                continue
            if cur is None:
                skipped.append(f"{rel} {k} {slot_name} is null (not created - §73a)")
                continue
            if not close(cur, was):
                problems.append(f"{rel} {k} {slot_name}: GUARD FAILED - current {cur}, expected was={was}")
                continue
            cell[idx] = now
            expect[rel].add((sym, qe))
            plan.append("%-32s %-11s %s %-4s %12s -> %-8s [mirror]" % (rel, sym, qe, slot_name, was, now))


# ---------------- blast radius ---------------------------------------------------------------
def diff_keys(rel):
    """Return the set of (sym, key) that actually differ between orig and work."""
    a, b, out = orig[rel], work[rel], set()
    for sym in set(a) | set(b):
        ra, rb = a.get(sym), b.get(sym)
        if ra == rb:
            continue
        if isinstance(ra, list) and isinstance(rb, list):
            ma = {r[0]: r for r in ra if isinstance(r, list) and r}
            mb = {r[0]: r for r in rb if isinstance(r, list) and r}
            for q in set(ma) | set(mb):
                if ma.get(q) != mb.get(q):
                    out.add((sym, q))
        elif isinstance(ra, dict) and isinstance(rb, dict):
            for q in set(ra) | set(rb):
                if ra.get(q) != rb.get(q):
                    out.add((sym, q))
        else:
            out.add((sym, None))
    return out


for rel in orig:
    got = diff_keys(rel)
    unexpected = got - expect[rel]
    if unexpected:
        problems.append(
            "%s BLAST RADIUS: %d unintended cell(s) changed: %s" % (rel, len(unexpected), sorted(unexpected)[:8])
        )

print("=" * 100)
for line in plan:
    print("  " + line)
print("-" * 100)
print("planned slot-writes: %d   skipped: %d   problems: %d" % (len(plan), len(skipped), len(problems)))
for s in skipped:
    print("  skip: " + s)
for p in problems:
    print("  PROBLEM: " + p)

if problems:
    print("\nABORTED - fix the problems above. Nothing written.")
    sys.exit(1)

if "--apply" not in sys.argv:
    print("\nDRY RUN. Re-run with --apply to write.")
    sys.exit(0)

# ---------------- journal ---------------------------------------------------------------------
pdp = os.path.join(HERE, "pat_defects.json")
pd = json.load(open(pdp, encoding="utf-8"))
srcs = V["sources"]
journalled = 0
for k, fix, kind in entries:
    sym, qe = k.split("|")
    e = V["cells"].get(k) or V["companions"].get(k)
    ent = pd.setdefault(sym, {}).setdefault(qe, {})
    if "std" in fix:
        ent["stored_pat"] = fix["std"][0]
        ent["correct_pat"] = fix["std"][1]
    if "con" in fix:
        ent["stored_pat_con"] = fix["con"][0]
        ent["correct_pat_con"] = fix["con"][1]
    ent["defect"] = "nosub_con_lag §73a ({}): {}".format(kind, e["defect"])
    ent["source"] = " || ".join(srcs[s] for s in e["src"])
    journalled += 1

for rel in FUND_TWINS + REVOP_TWINS:
    if diff_keys(rel):
        dump(rel, work[rel])
        print(f"wrote {rel}")
dump("scripts/pat_defects.json", pd, pretty=True)
print("journalled %d cells into scripts/pat_defects.json" % journalled)
