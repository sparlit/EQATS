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


#!/usr/bin/env python3
"""Restore fundamentals ann-dates the RETIRED 15:30 gate had pushed off a month-end (runbook §149).

MIDNIGHT VISIBILITY RULE (user decision 2026-09-23): a result counts for the CALENDAR DAY it was
broadcast, whatever the time — the user sells at the rebalance close and buys at the next session's
open, so a filing at 20:00 on the rebalance day is actionable. gate_1530.py (2026-07-08 → 2026-09-23)
did the opposite: a month-end cell whose scrip's BSE Result broadcasts that day were ALL after 15:30
was bumped to the next trading day. This is its exact mirror:

  for every ann cell sitting on the trading day (or weekday — update_fundamentals' old form) AFTER
  a month-end D, whose scrip's BSE broadcasts on D were all after 15:30  ->  restore the cell to D.

Same conservatism, inverted: no BSE record on D, or any broadcast on D before the close, means the
stored next-day date was never a gate bump (a genuine next-day filing or an NSE lag) — untouched.
Idempotent: a restored cell sits on D, no longer on D+1, so a second pass decides 0.

Usage:  python3 scripts/ungate_1530.py            # dry run (writes scripts/_ungate_restores.json)
        python3 scripts/ungate_1530.py --apply     # also rewrite docs/sf_fundamentals.json + scripts/fundamentals.json
Inputs: scripts/_gate_events.json  [[sym, monthEnd], ...] from `build_gate_events.py --calendar --ungate`
        scripts/_filing_times.json {monthEnd: {scripcode: [NEWS_DT, ...]}} (gunzipped filing_times_cache.json.gz,
                                   topped up by fetch_filing_times.py)
        scripts/_trading_days.json, scripts/bse_scrips.json (by_id: SYM -> scripcode)
"""
import bisect
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
CUTOFF_MIN = 15 * 60 + 30  # the retired gate's cutoff — needed to recognise what it bumped


def load(p):
    return json.load(open(p))


def news_min(ts):
    """Minutes-after-midnight from a BSE NEWS_DT like '2020-10-30T17:08:23.81'."""
    try:
        t = ts.split("T")[1]
        return int(t[0:2]) * 60 + int(t[3:5])
    except Exception:
        return None


def next_wd(d):
    x = datetime.date(d // 10000, d // 100 % 100, d % 100) + datetime.timedelta(days=1)
    while x.weekday() >= 5:
        x += datetime.timedelta(days=1)
    return x.year * 10000 + x.month * 100 + x.day


def main():
    apply = "--apply" in sys.argv
    events = [tuple(x) for x in load(os.path.join(HERE, "_gate_events.json"))]
    times = load(os.path.join(HERE, "_filing_times.json"))
    by_id = load(os.path.join(HERE, "bse_scrips.json"))["by_id"]
    tdays = load(os.path.join(HERE, "_trading_days.json"))  # sorted ints

    def next_td(d):
        i = bisect.bisect_right(tdays, d)
        return tdays[i] if i < len(tdays) else None

    def days_after(me):
        """§149 addendum: every calendar day after the month-end up to and including the next trading
        day (weekend + holidays + the next session), or the next weekday when no later bar exists yet.
        An after-close Friday filing is often stored on the Saturday/Sunday by NSE-archive-dated writers;
        the first mirror only looked at the next trading day / weekday and left 206 such cells behind."""
        nt = next_td(me)
        out = []
        d0 = datetime.date(me // 10000, me // 100 % 100, me % 100)
        for k in range(1, 8):
            x = d0 + datetime.timedelta(days=k)
            xi = x.year * 10000 + x.month * 100 + x.day
            if nt is None:
                if x.weekday() < 5:
                    out.append(xi)
                    break
                continue
            if xi > nt:
                break
            out.append(xi)
        return out

    restore = {}  # (sym, storedDate) -> monthEnd
    reasons = {"restorable": 0, "before_close": 0, "no_bse_record": 0, "no_scrip": 0}
    examples = []
    for sym, me in events:
        sc = by_id.get(sym)
        if sc is None:
            reasons["no_scrip"] += 1
            continue
        tl = (times.get(str(me), {}) or {}).get(str(sc))
        mins = [m for m in (news_min(t) for t in (tl or [])) if m is not None]
        if not mins:
            reasons["no_bse_record"] += 1
            continue
        if min(mins) <= CUTOFF_MIN:
            reasons["before_close"] += 1
            continue  # never bumped by the gate: leave the stored date alone
        for nd in days_after(me):
            restore[(sym, nd)] = me
        reasons["restorable"] += 1
        if len(examples) < 20:
            examples.append((sym, me, f"{min(mins) // 60:02d}:{min(mins) % 60:02d}"))

    print("=== decision summary (per (sym, month-end) event) ===")
    for k, v in reasons.items():
        print(f"  {k:16s} {v}")
    print(f"  total events     {len(events)}")
    print("\n=== sample restorable (sym, monthEnd, earliest BSE broadcast that day) ===")
    for e in examples:
        print("  ", *e)

    fpath = os.path.join(DOCS, "sf_fundamentals.json")
    fund = load(fpath)
    log = []
    for sym, rows in fund.items():
        for r in rows:
            for fld, idx in (("annStd", 2), ("annCon", 4)):
                if len(r) > idx and isinstance(r[idx], int) and (sym, r[idx]) in restore:
                    log.append({"sym": sym, "qe": r[0], "field": fld, "old": r[idx], "new": restore[(sym, r[idx])]})
    json.dump(log, open(os.path.join(HERE, "_ungate_restores.json"), "w"), separators=(",", ":"))
    print(f"\nrow-cells to restore: {len(log)} (written to scripts/_ungate_restores.json)")
    bad = [b for b in log if b["new"] >= b["old"]]
    if bad:
        print("INVARIANT VIOLATION — a restore must move a date EARLIER:", bad[:5])
        sys.exit(1)

    # JSL Sep-2020 was the gate's proof case (filed 30-Oct-2020 17:08, bumped to 2-Nov): the mirror's PASS
    # signal is that cell reading 20201030 again — as a restore now, or "already" on a later run.
    jsl = [r for r in fund.get("JSL", []) if r[0] == 20200930]
    print(
        "JSL Sep-2020 cell now:",
        [(r[2], r[4]) for r in jsl] or "NOT FOUND",
        "| restore queued:",
        [b for b in log if b["sym"] == "JSL" and b["qe"] == 20200930] or "none",
    )

    if not apply:
        print("\n(dry run — pass --apply to rewrite both fundamentals files)")
        return

    for path in (fpath, os.path.join(HERE, "fundamentals.json")):
        if not os.path.exists(path):
            print("skip (absent):", os.path.relpath(path, HERE))
            continue
        d = load(path)
        cnt = 0
        for sym, rows in d.items():
            for r in rows:
                for idx in (2, 4):
                    if len(r) > idx and isinstance(r[idx], int) and (sym, r[idx]) in restore:
                        r[idx] = restore[(sym, r[idx])]
                        cnt += 1
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print(f"restored {cnt} cells -> {os.path.relpath(path, HERE)}")
    print("DONE.")


if __name__ == "__main__":
    main()
