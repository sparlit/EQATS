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
"""Three-way merge so a CI refresh cannot clobber fills that landed while it was running.

THE BUG THIS FIXES (observed 2026-08-06). refresh-fundamentals.yml snapshots the payload files at
the start of its commit step, then inside its push-retry loop does:

    git fetch origin main && git reset --hard origin/main
    cp /tmp/sf_revop.json docs/sf_revop.json          # <-- blind restore of a STALE snapshot
    git add ... && git commit && git push

The reset correctly picks up whatever other writers landed, and the `cp` immediately throws it
away. A backfill session pushed 193 consolidated-revenue cells at ~12:5x; the 13:02 refresh had
snapshotted before that and silently reverted every one of them. The values survived only because
scripts/revop_fundamentals.json (the ledger) is deliberately NOT committed from CI.

WHY NOT A PLAIN FILL-ONLY MERGE. "Copy any non-null from the snapshot, keep origin otherwise" would
preserve concurrent fills but would also RESURRECT cells that CI deliberately nulled --
revop_sanity.py exists precisely to strip junk (a wrong-scale fill, a duplicate), and those nulls
must stick. Fill-only cannot tell "CI removed this" from "CI never had it".

THE THREE-WAY MERGE. With
    base   = the file as checked out at job start (before this job touched it)
    ours   = the file this job rebuilt
    theirs = the file currently on origin (after the reset)
decide per SLOT:
    ours != base  ->  this job changed the value on purpose  ->  take OURS (nulls included)
    ours == base  ->  this job did not touch it              ->  take THEIRS (concurrent fill survives)

That keeps every deliberate CI change, including deletions, while never discarding another writer's
work in a cell CI had no opinion about.

Handles both payload shapes:
    sf_revop.json        {sym: {qe: [9 slots]}}
    sf_fundamentals.json {sym: [[qe, stdPAT, stdAnn, conPAT, conAnn], ...]}

Usage:  python3 scripts/ci_preserve_merge.py <base> <ours> <theirs> <out>
Exit 0 always writes <out>; on any unexpected shape it falls back to OURS (previous behaviour), so
a surprise can never make the refresh worse than it was.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fund_dup_guard


def _rows_to_map(rows):
    """qe -> row. NOTE this is LAST-wins, while every consumer of sf_fundamentals reads the FIRST
    match (`next((r for r in rows if r[0] == qe), None)`). On a store carrying two rows for one
    quarter the two disagree, so the merge would write into a row nobody reads -- which is why
    main() deduplicates every input before merging (see scripts/fund_dup_guard.py)."""
    return {r[0]: r for r in rows if isinstance(r, list) and r}


def _predup(name, obj):
    """Merge conflict-free duplicate quarters out of a listrows payload, loudly. Never raises:
    this script's contract is that a surprise can never make the refresh worse than it was."""
    try:
        n, conflicts = fund_dup_guard.dedup(obj)
    except Exception as ex:  # pragma: no cover - defensive, see contract above
        print(f"ci_preserve_merge: dedup skipped for {name} ({type(ex).__name__}: {ex})")
        return obj
    if n or conflicts:
        print(
            "ci_preserve_merge: %s carried duplicate quarters -- %d merged, %d left as value "
            "conflicts%s"
            % (
                name,
                n,
                len(conflicts),
                "".join("\n    CONFLICT {} {} {}".format(c["sym"], c["qe"], c["conflicts"]) for c in conflicts),
            )
        )
    return obj


def merge_listrows(base, ours, theirs):
    """sf_fundamentals shape: {sym: [[qe, ...], ...]}"""
    out = copy.deepcopy(theirs)
    changed = kept = 0
    for sym, orows in ours.items():
        om, bm = _rows_to_map(orows), _rows_to_map(base.get(sym, []))
        tm = _rows_to_map(out.get(sym, []))
        for qe, orow in om.items():
            brow, trow = bm.get(qe), tm.get(qe)
            if trow is None:  # origin lacks the row entirely -> CI's row wins
                out.setdefault(sym, []).append(list(orow))
                changed += 1
                continue
            n = max(len(orow), len(trow))
            while len(trow) < n:
                trow.append(None)
            for i in range(1, min(n, len(orow))):
                bv = brow[i] if brow and i < len(brow) else None
                if orow[i] != bv:  # CI changed this slot on purpose
                    if trow[i] != orow[i]:
                        trow[i] = orow[i]
                        changed += 1
                else:  # CI untouched -> keep whatever origin has
                    kept += 1
    return out, changed, kept


def merge_qmaps(base, ours, theirs):
    """sf_revop shape: {sym: {qe: [slots]}}"""
    out = copy.deepcopy(theirs)
    changed = kept = 0
    for sym, qm in ours.items():
        for qe, orow in qm.items():
            brow = (base.get(sym) or {}).get(qe)
            trow = (out.get(sym) or {}).get(qe)
            if trow is None:
                out.setdefault(sym, {})[qe] = list(orow)
                changed += 1
                continue
            n = max(len(orow), len(trow))
            while len(trow) < n:
                trow.append(None)
            for i in range(min(n, len(orow))):
                bv = brow[i] if brow and i < len(brow) else None
                if orow[i] != bv:
                    if trow[i] != orow[i]:
                        trow[i] = orow[i]
                        changed += 1
                else:
                    kept += 1
            out[sym][qe] = trow
    return out, changed, kept


def main():
    base_p, ours_p, theirs_p, out_p = sys.argv[1:5]
    ours = json.load(open(ours_p))
    try:
        base = json.load(open(base_p))
    except Exception:
        base = {}
    try:
        theirs = json.load(open(theirs_p))
    except Exception:
        theirs = {}
    try:
        sample = next(iter(ours.values())) if ours else None
        if isinstance(sample, dict):
            out, ch, kept = merge_qmaps(base, ours, theirs)
        elif isinstance(sample, list):
            base = _predup("base", base)
            ours = _predup("ours", ours)
            theirs = _predup("theirs", theirs)
            out, ch, kept = merge_listrows(base, ours, theirs)
            out = _predup("merged", out)
        else:
            msg = "unrecognised payload shape"
            raise ValueError(msg)
    except Exception as ex:
        # Never make the refresh worse than the old blind copy: fall back to OURS.
        print(f"ci_preserve_merge: FALLBACK to ours ({type(ex).__name__}: {ex})")
        json.dump(ours, open(out_p, "w"), separators=(",", ":"))
        return
    json.dump(out, open(out_p, "w"), separators=(",", ":"))
    print("ci_preserve_merge %s: %d slots from this run, %d left as origin had them" % (out_p.split("/")[-1], ch, kept))


if __name__ == "__main__":
    main()
