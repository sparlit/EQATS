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
"""Cell-level UNION of a job's docs/bse_fundamentals.json into the current one (runbook §181b).

refresh-bse.yml used to `cp` its whole file over origin's at commit time, silently erasing every quarter another writer
(bse-results-xbrl.yml, the bse-fund-history merges, vision merges) landed while it ran. This merges instead:
cells only the job has are ADDED; where both hold a cell the CURRENT (origin) one wins — the job's own fetch is
fill-only, so a differing cell means someone else changed it after the job checked out.

THREE-WAY with --base <sha> (2026-09-27): only cells the JOB CHANGED relative to the commit it started from
are considered. A two-way union re-added whatever origin had removed or cleared meanwhile — a job that
checked out before the §187 heal would have put back all 1,805 fake 2026-06-15 dates ("a date origin lacks").

Run: python3 scripts/union_bse_fundamentals.py <job_copy.json> [target=docs/bse_fundamentals.json] [--base SHA]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qe_util as QU

HERE = os.path.dirname(os.path.abspath(__file__))


def _base_px(sha):
    """px of docs/bse_fundamentals.json at `sha` (the job's starting commit), or None when unreadable."""
    import subprocess

    try:
        raw = subprocess.run(
            ["git", "show", f"{sha}:docs/bse_fundamentals.json"],
            capture_output=True,
            check=True,
            cwd=os.path.join(HERE, ".."),
        ).stdout
        return json.loads(raw).get("px") or {}
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = None
    if "--base" in sys.argv:
        base = _base_px(sys.argv[sys.argv.index("--base") + 1])
        args = [a for a in args if a != sys.argv[sys.argv.index("--base") + 1]]
        if base is None:
            print("union_bse_fundamentals: base unreadable — two-way fallback")
    mine_p = args[0]
    tgt_p = args[1] if len(args) > 1 else os.path.join(HERE, "..", "docs", "bse_fundamentals.json")
    mine = json.load(open(mine_p, encoding="utf-8"))
    try:
        cur = json.load(open(tgt_p, encoding="utf-8"))
    except (OSError, ValueError):
        cur = {"px": {}}
    px = cur.setdefault("px", {})
    added = kept = 0
    for code, qmap in (mine.get("px") or {}).items():
        dst = px.setdefault(code, {})
        for qe, cell in qmap.items():
            if not str(qe).isdigit() or not QU.is_qe(int(qe)):
                continue  # an OCR-garbled key (26310331)
            if base is not None and (base.get(code) or {}).get(qe) == cell:
                continue  # the job did not change this cell: origin's version (heal, removal) stands
            if qe in dst:
                old = dst[qe]
                # a figure origin's cell LACKS (e.g. a revenue-only vision read) may be added, same basis only
                if old.get("basis", cell.get("basis")) == cell.get("basis"):
                    for k in ("pat", "rev", "op"):
                        if old.get(k) is None and cell.get(k) is not None:
                            old[k] = cell[k]
                            added += 1
                    if not old.get("ann") and cell.get("ann"):
                        old["ann"] = cell["ann"]
                        added += 1  # a date origin lacks
                kept += old != cell
                continue
            dst[qe] = cell
            added += 1
    if mine.get("updated") and mine["updated"] > (cur.get("updated") or ""):
        cur["updated"] = mine["updated"]
    json.dump(cur, open(tgt_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(
        "union_bse_fundamentals: +%d cells from the job; %d differing cells kept as current"
        % (added, kept)
    )


if __name__ == "__main__":
    main()
