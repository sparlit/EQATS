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
"""Three-way merge of the BSE grind's resume ledgers into origin's copies (refresh-bse.yml commit step).

_bse_fund_done.json / _bse_fund_fail.json are ALSO written by merge_bse_vision.py (the bse-vision-fill
routine lands its PR while the grind runs). The commit step used to `cp` the job's copies over origin's
after `reset --hard`, silently undoing every routine update made meanwhile (a filled scrip's fail count
came back, it re-entered the grind queue). This keeps only what THIS job changed relative to the commit
it started from, applied on top of origin's current copy:

  list (done):  (origin ∪ job-added) − job-removed
  dict (fail/seen): each key the job changed (set, altered or deleted) takes the job's value; every other
                    key keeps origin's.

Run: python3 scripts/merge_bse_ledgers.py <base-sha> <job-copies-dir>
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGERS = [
    "scripts/_bse_fund_done.json",
    "scripts/_bse_fund_fail.json",
    "scripts/_bse_fund_seen.json",
]


def _load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def _at(sha, rel):
    try:
        return json.loads(
            subprocess.run(
                ["git", "show", f"{sha}:{rel}"],
                capture_output=True,
                check=True,
                cwd=os.path.join(HERE, ".."),
            ).stdout
        )
    except (subprocess.CalledProcessError, ValueError):
        return None


def merge3(base, mine, cur):
    """Apply the base→mine change set onto cur. None = file absent."""
    if mine is None:
        return cur  # the job never wrote this ledger
    if isinstance(mine, list):
        b, m, c = set(base or []), set(mine), set(cur or [])
        return sorted((c | (m - b)) - (b - m))
    b, c = base or {}, dict(cur or {})
    for k in set(b) | set(mine):
        if mine.get(k) != b.get(k):
            if k in mine:
                c[k] = mine[k]
            else:
                c.pop(k, None)
    return c


def main():
    sha, job_dir = sys.argv[1], sys.argv[2]
    root = os.path.join(HERE, "..")
    for rel in LEDGERS:
        mine = _load(os.path.join(job_dir, os.path.basename(rel)))
        tgt = os.path.join(root, rel)
        out = merge3(_at(sha, rel), mine, _load(tgt))
        if out is None:
            continue
        kw = {"sort_keys": True} if isinstance(out, dict) else {}
        json.dump(out, open(tgt, "w"), **kw)
        print("merge_bse_ledgers: %s -> %d entries" % (rel, len(out)))


if __name__ == "__main__":
    main()
