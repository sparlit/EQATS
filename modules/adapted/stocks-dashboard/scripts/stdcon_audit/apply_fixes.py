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
"""Apply the std-slot-holds-con corrections in scripts/stdcon_fixes.json (runbook §2b + §59).

This OVERWRITES non-null stored values, so it runs the §2b guard discipline in full:
  * load every target file FRESH (a concurrent session may have moved it since the audit),
  * ASSERT the old value is still exactly what the ledger says before touching it -- a cell whose
    stored value has changed is REPORTED and SKIPPED, never forced,
  * change ONLY the standalone PAT slot; the consolidated slot is correct in every one of these
    cells and is left alone, as are both announce dates (the std figure comes from the same filing),
  * after editing, DIFF the whole structure against the pre-edit copy and abort unless the only
    differences are the intended cells,
  * write minified, exactly as the pipeline does.

Four files, because the fundamentals pair feeds the site and the revop pair feeds the stock page:
    docs/sf_fundamentals.json      row [qe, patStd, dateStd, patCon, dateCon]   -> idx 1
    scripts/fundamentals.json      same shape (mirror)                          -> idx 1
    docs/sf_revop.json             {qe: [revS, revC, opS, opC, patS, patC, ...]} -> idx 4
    scripts/revop_fundamentals.json   the LEDGER sf_revop is rebuilt from        -> idx 4
CLAUDE.md rule 5: healing the derived file alone would be undone by the nightly rebuild, so the
revop LEDGER is the one that actually matters -- the derived copy is patched too so the site is
correct before the next rebuild rather than after it.

Run:  python3 -X utf8 scripts/stdcon_audit/apply_fixes.py [--apply]      (default DRY RUN)
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "stdcon_fixes.json")
FUND = [(os.path.join(ROOT, "docs", "sf_fundamentals.json"), 1), (os.path.join(SCRIPTS, "fundamentals.json"), 1)]
REVOP = [(os.path.join(ROOT, "docs", "sf_revop.json"), 4), (os.path.join(SCRIPTS, "revop_fundamentals.json"), 4)]
EPS = 0.005


def near(a, b):
    return a is not None and b is not None and abs(a - b) < EPS


def main():
    apply_ = "--apply" in sys.argv
    cells = json.load(open(LEDGER))["cells"]
    print("cells in ledger: %d   mode: %s\n" % (len(cells), "APPLY" if apply_ else "DRY RUN"))
    report, blocked = [], 0

    for path, idx in FUND:
        d = json.load(open(path))
        before = copy.deepcopy(d)
        touched = []
        for c in cells:
            rows = d.get(c["sym"]) or []
            row = next((r for r in rows if r[0] == c["qe"]), None)
            tag = "{} {} {}".format(os.path.basename(path), c["sym"], c["qe"])
            if row is None:
                report.append("  SKIP  %-44s no row" % tag)
                continue
            if not near(row[idx], c["old_std"]):
                report.append(
                    "  BLOCK %-44s stored std is %s, ledger expects %s -- NOT touched" % (tag, row[idx], c["old_std"])
                )
                blocked += 1
                continue
            if len(row) > 3 and not near(row[3], c["con"]):
                report.append(
                    "  BLOCK %-44s con slot is %s, ledger expects %s -- NOT touched" % (tag, row[3], c["con"])
                )
                blocked += 1
                continue
            row[idx] = c["new_std"]
            touched.append((c["sym"], c["qe"]))
            report.append(
                "  FIX   %-44s std %s -> %s   (con %s left as filed)" % (tag, c["old_std"], c["new_std"], c["con"])
            )
        assert_only(before, d, touched, path, idx, kind="fund")
        if apply_ and touched:
            json.dump(d, open(path, "w"), separators=(",", ":"))

    for path, idx in REVOP:
        d = json.load(open(path))
        before = copy.deepcopy(d)
        touched = []
        for c in cells:
            row = (d.get(c["sym"]) or {}).get(str(c["qe"]))
            tag = "{} {} {}".format(os.path.basename(path), c["sym"], c["qe"])
            if row is None:
                report.append("  skip  %-44s no revop row (not created)" % tag)
                continue
            cur = row[idx]
            if cur is None:
                row[idx] = c["new_std"]
                touched.append((c["sym"], c["qe"]))
                report.append("  fill  %-44s patStd None -> %s" % (tag, c["new_std"]))
            elif near(cur, c["old_std"]):
                row[idx] = c["new_std"]
                touched.append((c["sym"], c["qe"]))
                report.append("  FIX   %-44s patStd %s -> %s" % (tag, cur, c["new_std"]))
            elif near(cur, c["new_std"]):
                report.append("  ok    %-44s patStd already %s" % (tag, cur))
            else:
                report.append(
                    "  BLOCK %-44s patStd is %s, expected %s or %s -- NOT touched"
                    % (tag, cur, c["old_std"], c["new_std"])
                )
                blocked += 1
        assert_only(before, d, touched, path, idx, kind="revop")
        if apply_ and touched:
            json.dump(d, open(path, "w"), separators=(",", ":"))

    print("\n".join(report))
    print("\nblocked: %d" % blocked)
    if not apply_:
        print("DRY RUN -- nothing written. Re-run with --apply.")


def assert_only(before, after, touched, path, idx, kind):
    """Abort unless the ONLY differences between before/after are the cells we meant to change."""
    want = {(s, q) for s, q in touched}
    diffs = []
    keys = set(before) | set(after)
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b == a:
            continue
        if kind == "fund":
            bi = {r[0]: r for r in (b or [])}
            ai = {r[0]: r for r in (a or [])}
            for qe in set(bi) | set(ai):
                if bi.get(qe) != ai.get(qe):
                    diffs.append((k, qe, bi.get(qe), ai.get(qe)))
        else:
            for qe in set(b or {}) | set(a or {}):
                if (b or {}).get(qe) != (a or {}).get(qe):
                    diffs.append((k, int(qe), (b or {}).get(qe), (a or {}).get(qe)))
    unexpected = [d for d in diffs if (d[0], d[1]) not in want]
    if unexpected:
        msg = f"ABORT {os.path.basename(path)}: unexpected diffs {unexpected[:4]}"
        raise SystemExit(msg)
    for sym, qe, b, a in diffs:  # and each intended diff must be ONE slot
        changed = [i for i in range(max(len(b or []), len(a or []))) if (b or [None] * 9)[i] != (a or [None] * 9)[i]]
        if changed != [idx]:
            raise SystemExit(
                "ABORT %s: %s %s changed slots %s, expected only [%d]" % (os.path.basename(path), sym, qe, changed, idx)
            )
    print("  [%s] %d cell(s) changed, no collateral edits" % (os.path.basename(path), len(diffs)))


main()
