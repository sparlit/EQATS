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
"""Results (revenue, PAT, filing date) of EVERY BSE SME IPO member since 2020, from BSE's own XBRL filings, point in time
(user, 2026-09-27: "fetch fundamentals of all bse sme ipo point in time from 2020 till date"). Runbook §195.

A driver around scripts/fetch_bse_results_xbrl.py — same listing route, same parsers, same SME half-year rules
(sme_decide: the year's arithmetic, provisional H1 per Option A), same fill-only --apply. What it changes is WHO and WHICH
periods: its own targets are the 504 scrips in docs/bse_sme_ipo/stints.json (members 2020→, incl. those that later
migrated to the main board, moved to NSE or were delisted — the daily job's targets() only walks today's BSE-only
universe), and each scrip's SME-ERA half-years only (Sep/Mar period ends from its listing until it left the SME groups,
per the member price ledger's group history) that bse_fundamentals / sf_fundamentals do not already hold. A migrated
scrip's later main-board quarters are NOT asked here: its current group is main-board, and the reader's quarterly path
would read an SME half-year file's OneD as a quarter. The daily job's 20-day re-list pause is lifted for this run.

  python3 scripts/fetch_bse_sme_ipo_fundamentals.py --plan              (print targets, no requests)
  python3 scripts/fetch_bse_sme_ipo_fundamentals.py --fetch FILLS [--limit N]
  python3 scripts/fetch_bse_results_xbrl.py --apply FILLS               (fill-only merge — run on a fresh main)
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("BSE_XBRL_MAX_FILES", "100000")
import bse_sme_ipo_px as PX
import fetch_bse_results_xbrl as X

ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
FLOOR = 20200331
LAG = 60  # a half-year's results are due within 45 days of its end; ask only once 60 have passed


def half_ends(frm, to):
    out = []
    for y in range(frm // 10000 - 1, to // 10000 + 1):
        for q in (y * 10000 + 930, (y + 1) * 10000 + 331):
            if (
                q >= FLOOR and frm <= q + 10000 and q <= to
            ):  # (listing mid-half: that half is still reportable)
                out.append(q)
    return sorted(set(out))


def plan():
    today = datetime.date.today()
    cutoff = int((today - datetime.timedelta(days=LAG)).strftime("%Y%m%d"))
    st = json.load(open(os.path.join(DOCS, "bse_sme_ipo", "stints.json")))["stints"]
    bf = json.load(open(os.path.join(DOCS, "bse_fundamentals.json"), encoding="utf-8")).get(
        "px", {}
    )
    sf = json.load(open(os.path.join(DOCS, "sf_fundamentals.json")))
    L = PX.load()["px"]
    first = {}
    for s in st:
        if s["code"] not in first or (s.get("listing") or s["join"]) < (
            first[s["code"]].get("listing") or first[s["code"]]["join"]
        ):
            first[s["code"]] = s
    tl, stats = [], {"members": len(first), "due": 0, "have": 0, "ask": 0, "no_era": 0}
    for code, s in sorted(first.items()):
        listing = int((s.get("listing") or s["join"]).replace("-", ""))
        e = L.get(code)
        sme_end = cutoff
        if e and e.get("g"):
            g = X.SME_GROUPS
            runs = e["g"]  # [[i, group]…] change list
            last_sme_i = None
            for j, (_i, grp) in enumerate(runs):
                if grp in g:
                    end_i = (runs[j + 1][0] - 1) if j + 1 < len(runs) else len(e["d"]) - 1
                    last_sme_i = end_i
            if last_sme_i is not None and last_sme_i < len(e["d"]) - 1:
                sme_end = min(
                    cutoff, e["d"][last_sme_i]
                )  # left the SME groups: its halves up to that day
        due = [q for q in half_ends(listing, sme_end) if q <= cutoff]
        cells = bf.get(code) or {}
        tk = s.get("id")
        sfq = (
            {r[0] for r in sf.get(tk, []) if r[1] is not None or r[3] is not None} if tk else set()
        )
        have = [
            q
            for q in due
            if (
                isinstance(cells.get(str(q)), dict)
                and not cells[str(q)].get("prov")
                and (cells[str(q)].get("pat") is not None or cells[str(q)].get("rev") is not None)
            )
            or q in sfq
        ]
        miss = [q for q in due if q not in have]
        stats["due"] += len(due)
        stats["have"] += len(have)
        stats["ask"] += len(miss)
        if not due:
            stats["no_era"] += 1
        if miss:
            tl.append((code, None, "bse", True, miss))
    return tl, stats


def main():
    a = sys.argv[1:]
    tl, stats = plan()
    print(
        "plan: %(members)d members, %(due)d SME-era half-years due, %(have)d stored, %(ask)d to ask"
        % stats,
        "(%d scrips)" % len(tl),
    )
    if "--plan" in a:
        for t in tl[:15]:
            print("  ", t[0], t[4])
        return
    if "--fetch" in a:
        out = a[a.index("--fetch") + 1]
        if "--limit" in a:
            tl = tl[: int(a[a.index("--limit") + 1])]
        X.targets = lambda today: tl  # our targets, the reader's everything else
        X.RELIST_DAYS = 0  # no 20-day pause for this run
        X.fetch(len(tl) + 1, out)


if __name__ == "__main__":
    main()
