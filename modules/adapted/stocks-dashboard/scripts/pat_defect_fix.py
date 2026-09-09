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
"""Apply `scripts/pat_defects.json` — the reviewed ledger of stored PAT cells proven WRONG against a
primary document — to the built fundamentals JSONs (DATA_RUNBOOK §45 / §2b).

WHY THIS FILE EXISTS. `pat_defects.json` has been tracked since the §45 year-shift campaign, but its
applier (`_pat_defect_fix.py`) only ever lived in the rev-mission worktree, which is gone — so the
ledger was a journal with no way to replay it. That is the trap in memory
`feedback-reset-replay-hits-tracked-scripts`: a heal whose applier is not tracked cannot be re-run
after a reset, and a heal you cannot re-run is not a heal. This is the in-repo, tracked replacement.

CONTRACT — it can only ever narrow, never invent:
  * A slot is touched ONLY when it still holds the exact value the ledger RECORDED as wrong
    (`stored_pat` -> npStd, `stored_pat_con` -> npCon). Anything else — a later correct value, a
    different heal, a null — is left alone and reported as `skip`. That makes the run idempotent and
    safe against a stale local copy: rerunning changes nothing, and a cell some other lane already
    fixed is never clobbered.
  * `correct_pat` / `correct_pat_con` may be `null`, which nulls the slot — the honest heal when a
    document proves the stored figure wrong but no trustworthy replacement exists (the ASTERDM con
    case). `None` is therefore a legal target and is distinguished from "key absent".
  * Rows are matched on the quarter-end only; no row is created. A ledger cell whose quarter is not
    in the series is reported as `no-row`, never appended (a missing quarter is a FILL, and fills go
    through the fill ledgers with their own anchor rules).

Both files are written: docs/sf_fundamentals.json (what the site + slices read) and
scripts/fundamentals.json (the build mirror) — they hold the same quantity and must not diverge
(memory `feedback-two-files-one-quantity`).

Run:  python -X utf8 scripts/pat_defect_fix.py            # dry run, prints every planned change
      python -X utf8 scripts/pat_defect_fix.py --apply
      python -X utf8 scripts/pat_defect_fix.py --only LANCER[,SYM...]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "pat_defects.json")
TARGETS = [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(HERE, "fundamentals.json")]

# fundamentals row: [qe, npStd, annStd, npCon, annCon]
SLOTS = [("std", "stored_pat", "correct_pat", 1), ("con", "stored_pat_con", "correct_pat_con", 3)]
EPS = 0.005  # stored values are 2-dp crore; this is half a last digit


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= EPS
    except (TypeError, ValueError):
        return False


def load_ledger(only=None):
    d = json.load(open(LEDGER, encoding="utf-8"))
    out = []
    for sym, cells in d.items():
        if sym.startswith("_") or not isinstance(cells, dict):
            continue  # _README and friends
        if only and sym not in only:
            continue
        for qe, e in cells.items():
            out.append((sym, str(qe), e))
    return out


def apply_file(path, entries, write):
    if not os.path.exists(path):
        return [("-", "-", "MISSING FILE")], 0
    data = json.load(open(path, encoding="utf-8"))
    log, changed = [], 0
    for sym, qe, e in entries:
        rows = [r for r in data.get(sym, []) if str(r[0]) == qe]
        if not rows:
            log.append((sym, qe, "no-row"))
            continue
        for row in rows:
            for basis, was_key, want_key, idx in SLOTS:
                if want_key not in e:
                    continue  # this basis is not part of the heal
                was, want = e.get(was_key), e.get(want_key)
                if _same(row[idx], want):
                    log.append((sym, qe, f"already {basis}={want!r}"))
                elif _same(row[idx], was):
                    log.append((sym, qe, f"{basis} {row[idx]!r} -> {want!r}"))
                    row[idx] = want
                    changed += 1
                else:
                    log.append((sym, qe, f"SKIP {basis}: holds {row[idx]!r}, ledger recorded {was!r}"))
    if write and changed:
        json.dump(data, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    return log, changed


def main():
    write = "--apply" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    entries = load_ledger(only)
    print(
        "%d ledger cell(s)%s | %s"
        % (len(entries), " for " + ",".join(sorted(only)) if only else "", "APPLY" if write else "DRY RUN")
    )
    for path in TARGETS:
        log, changed = apply_file(path, entries, write)
        print("  %-46s %d change(s)" % (os.path.basename(path), changed))
        for sym, qe, msg in log:
            if only or not msg.startswith("already"):
                print("      %-11s %-9s %s" % (sym, qe, msg))
    if not write:
        print("(dry run — nothing written; add --apply)")


if __name__ == "__main__":
    main()
