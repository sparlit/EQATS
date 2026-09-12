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
"""ONE row per (symbol, quarter-end) in docs/sf_fundamentals.json — guard + merger.

THE BUG THIS FIXES (found 2026-08-25). Row shape is [qe, npStd, annStd, npCon, annCon] and
EVERY consumer resolves a quarter with the first-match idiom

    next((r for r in fund[sym] if r[0] == qe), None)

so a second row for the same quarter is invisible to readers and poisonous to writers: a
consolidated value written to `SYM|QE` can land on a standalone-only row (or read None) and
silently do nothing. scripts/apply_fund_cell_fix.py and scripts/apply_owners_full.py both use
that idiom.

WHERE THE DUPLICATES CAME FROM. scripts/_apply_reads.py's `main_pre2015` gated its "create the
PAT row" branch on `row is not None and row[1] is not None`, so the else covered TWO cases:
"no row for this quarter" (create — correct) AND "a CON-ONLY row exists whose std slot is empty"
(should fill in place — instead it appended a second row). Measured: all 22 duplicated quarters
across SUNPHARMA/CARBORUNIV/ADVANTA/APOLLOTYRE had, in the introducing commit's parent, exactly
one con-only row with an empty std slot. The `fmap[qe] = newrow` that follows then re-points the
map at the appended row, so later con fills land there while the ORIGINAL con row stays first —
which is exactly the row `next()` hands every reader. The sibling appliers
(apply_fav14_pat_std / apply_early_backfill / hist_backfill) all check for the existing row
first; that one path did not.

MERGE RULE — never invent a value:
  * a slot that is None in every duplicate row stays None;
  * a slot with exactly one distinct non-null value takes it;
  * a slot with TWO different non-null values is a CONFLICT — the quarter is left untouched and
    reported for adjudication. It is never silently picked.

Known, still-unadjudicated conflicts live in scripts/fund_dup_allow.json so the guard can stay
hard-failing for anything NEW without reddening CI over an old open question.

Run:  python3 scripts/fund_dup_guard.py [path]            # report only
      python3 scripts/fund_dup_guard.py [path] --merge     # merge conflict-free duplicates
      python3 scripts/fund_dup_guard.py [path] --json      # machine-readable report
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
ALLOW = os.path.join(HERE, "fund_dup_allow.json")  # NOT scripts/_* -- that prefix is gitignored

SLOTS = ("npStd", "annStd", "npCon", "annCon")  # row = [qe, npStd, annStd, npCon, annCon]


class DuplicateQuarterError(Exception):
    """Raised by assert_ok() when a store carries an unregistered duplicate quarter."""


def find_dups(fund):
    """-> {sym: {qe: [row, ...]}} for every quarter carrying more than one row."""
    out = {}
    for sym, rows in fund.items():
        if not isinstance(rows, list):
            continue
        by = collections.defaultdict(list)
        for r in rows:
            if isinstance(r, list) and r:
                by[r[0]].append(r)
        d = {qe: v for qe, v in by.items() if len(v) > 1}
        if d:
            out[sym] = d
    return out


def merge_rows(rows):
    """Slot-wise union of duplicate rows -> (merged, conflicts).

    `merged` is only valid when `conflicts` is empty — on a conflict the caller must leave the
    quarter alone rather than ship a row with the disputed slot blanked.
    """
    width = max(len(r) for r in rows)
    merged = [rows[0][0]] + [None] * (width - 1)
    conflicts = []
    for i in range(1, width):
        vals = []
        for r in rows:
            v = r[i] if i < len(r) else None
            if v is not None and v not in vals:
                vals.append(v)
        if len(vals) == 1:
            merged[i] = vals[0]
        elif len(vals) > 1:
            conflicts.append((SLOTS[i - 1] if i - 1 < len(SLOTS) else "idx%d" % i, vals))
    return merged, conflicts


def dedup(fund):
    """Merge every conflict-free duplicate quarter IN PLACE -> (n_merged, conflicts).

    The merged row keeps the FIRST duplicate's position, so a store that was sorted by quarter
    end stays sorted and `next()` readers keep resolving the same slot in the series.
    """
    n_merged = 0
    conflicts = []
    for sym in sorted(fund):
        rows = fund[sym]
        if not isinstance(rows, list):
            continue
        pos = collections.defaultdict(list)
        for i, r in enumerate(rows):
            if isinstance(r, list) and r:
                pos[r[0]].append(i)
        drop = set()
        for qe in sorted(pos):
            idxs = pos[qe]
            if len(idxs) < 2:
                continue
            group = [rows[i] for i in idxs]
            merged, cf = merge_rows(group)
            if cf:
                conflicts.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "rows": [list(g) for g in group],
                        "conflicts": [{"slot": s, "values": v} for s, v in cf],
                    }
                )
                continue
            rows[idxs[0]] = merged
            drop.update(idxs[1:])
            n_merged += 1
        if drop:
            fund[sym] = [r for i, r in enumerate(rows) if i not in drop]
    sort_rows(fund)  # rows MUST end sorted by quarter-end: the backtest engine finds the "current"
    # quarter by scanning BACKWARDS from the array end (profitAt/profitMetrics),
    # so an out-of-order tail makes it serve a stale quarter. ci_preserve_merge's
    # merge_listrows appends a CI-only quarter to the end without re-sorting, which
    # left 8 symbols out of order (STCINDIA `…20260630, 20260331`; audit 2026-09-01).
    return n_merged, conflicts


def sort_rows(fund):
    """Sort every symbol's rows by quarter-end (ascending) IN PLACE. Stable, so registered
    duplicate rows for one quarter keep their relative order. Returns the count of symbols that
    were out of order."""
    n = 0
    for rows in fund.values():
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        keys = [r[0] for r in rows if isinstance(r, list) and r]
        if keys != sorted(keys):
            rows.sort(key=lambda r: r[0] if isinstance(r, list) and r else 0)
            n += 1
    return n


def unsorted_symbols(fund):
    """-> sorted [sym, ...] whose rows are NOT in non-decreasing quarter-end order."""
    out = []
    for sym, rows in fund.items():
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        keys = [r[0] for r in rows if isinstance(r, list) and r]
        if keys != sorted(keys):
            out.append(sym)
    return sorted(out)


def load_allow(path=ALLOW):
    """-> set of "SYM|QE" duplicates that are known, reported and awaiting adjudication."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return set()
    return set(d.get("pending", {}))


def offenders(fund, allow=None):
    """-> sorted ["SYM|QE", ...] duplicates that are NOT on the allowlist."""
    allow = load_allow() if allow is None else allow
    return sorted(f"{sym}|{qe}" for sym, d in find_dups(fund).items() for qe in d if f"{sym}|{qe}" not in allow)


def assert_ok(fund, where="sf_fundamentals"):
    """Raise DuplicateQuarterError if `fund` carries an unregistered duplicate quarter.

    Call this on the way OUT of any writer, so a duplicate can never reach the file that every
    consumer reads with next().
    """
    bad = offenders(fund)
    if bad:
        raise DuplicateQuarterError(
            "%s: %d quarter(s) carry more than one row -- %s%s. "
            "Fix the writer, then `python3 scripts/fund_dup_guard.py --merge`; register a genuine "
            "value conflict in scripts/fund_dup_allow.json instead of merging it."
            % (where, len(bad), ", ".join(bad[:10]), " ..." if len(bad) > 10 else "")
        )
    # Out-of-order rows are WARNED, never raised: a raise here is too fragile — the live store
    # carries 8 legacy out-of-order symbols, so any caller that runs assert_ok before its store is
    # sorted crashes (it failed the nightly refresh on a mid-deploy race, 2026-09-01). The fix for
    # the ORDER invariant is the writers calling sort_rows() (dedup / update_fundamentals /
    # build_fundamentals all do), NOT a hard gate here. Duplicates stay a hard error above.
    unsorted = unsorted_symbols(fund)
    if unsorted:
        print(
            "[fund_dup_guard] WARN %s: %d symbol(s) out of quarter-end order -- %s%s "
            "(call sort_rows() before writing; not fatal)"
            % (where, len(unsorted), ", ".join(unsorted[:10]), " ..." if len(unsorted) > 10 else "")
        )
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else FUND
    fund = json.load(open(path, encoding="utf-8"))
    before = sum(len(v) for v in fund.values() if isinstance(v, list))
    dups = find_dups(fund)
    n_q = sum(len(d) for d in dups.values())
    n_extra = sum(len(v) - 1 for d in dups.values() for v in d.values())
    unsorted = unsorted_symbols(fund)
    print(
        "%s: %d symbols, %d rows | %d symbols carry %d duplicated quarter-ends (%d extra rows) | "
        "%d symbols OUT OF ORDER"
        % (os.path.relpath(path, ROOT), len(fund), before, len(dups), n_q, n_extra, len(unsorted))
    )
    if unsorted:
        print(
            "  out-of-order (engine serves a stale quarter for these): {}{}".format(
                ", ".join(unsorted[:20]), " ..." if len(unsorted) > 20 else ""
            )
        )

    preview = json.loads(json.dumps(fund))
    n_merged, conflicts = dedup(preview)
    if "--json" in sys.argv:
        print(json.dumps({"mergeable": n_merged, "conflicts": conflicts}, indent=2))
        return 0
    for sym in sorted(dups):
        for qe in sorted(dups[sym]):
            print("  %-12s %s" % (sym, qe))
            for r in dups[sym][qe]:
                print(f"      {r}")
    print("\nconflict-free and mergeable : %d quarters" % n_merged)
    print("genuine conflicts           : %d  (never merged -- adjudicate)" % len(conflicts))
    for c in conflicts:
        print("  *** {} {}".format(c["sym"], c["qe"]))
        for s in c["conflicts"]:
            print("      %-7s %s" % (s["slot"], s["values"]))
        for r in c["rows"]:
            print(f"      row {r}")
    if "--merge" in sys.argv:
        after = sum(len(v) for v in preview.values() if isinstance(v, list))
        json.dump(preview, open(path, "w"), separators=(",", ":"))
        print(
            "\nWROTE %s: %d rows -> %d (%d merged, %d conflicts left in place)"
            % (os.path.relpath(path, ROOT), before, after, n_merged, len(conflicts))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
