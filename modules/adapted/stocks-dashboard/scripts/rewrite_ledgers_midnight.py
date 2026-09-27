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
"""One-off (kept for the record; idempotent) — rewrite the visibility-date LEDGERS from the retired
15:30 gate to the MIDNIGHT rule (runbook §149, user decision 2026-09-23: a filing counts for the
calendar day it was broadcast, whatever the time — the user buys at the next session's open).

Ledgers and what changes (every rewritten entry keeps the old value and is tagged `rule`):
  scripts/shp_lag_fix.json      entry with `ts` whose `sub` == the retired gate's form of ts
                                -> sub = calendar day of ts, sub_1530 = old sub, days_later recomputed
  scripts/shp_sub_dates.json    same
  scripts/ann_date_fills.json   `exact` entry whose src note reads "... NEWS_DT <ts> -> gated <ann>"
                                -> ann = calendar day of that ts, ann_1530 = old ann
  scripts/bse_result_fills.json entry with `filed` (BSE DT_TM) -> ann = calendar day of it, ann_1530 = old
  scripts/ann_cell_fix.json     REPORTED only (1 reviewed entry) — hand-check its timestamp
An entry whose sub/ann is NEITHER the raw day NOR the retired gate's form of its own timestamp is an
anomaly: reported, never touched (a different source's date is not this rule's business).

Dry run by default:  python3 scripts/rewrite_ledgers_midnight.py
Apply:               python3 scripts/rewrite_ledgers_midnight.py --apply
Then: fetch_shareholding.py --feed-only (SHP), build_gate_events --calendar --ungate + ungate_1530 --apply
(fundamentals cells) — see PLAN_MIDNIGHT_VISIBILITY.md.
"""
import bisect
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULE = "midnight-2026-09-23"
CAL = json.load(open(os.path.join(HERE, "gate_calendar.json")))["tdays"]
CALSET = set(CAL)
TS_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})")


def parse_ts(ts):
    m = TS_RE.match(str(ts or ""))
    if not m:
        return None, None
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3)), int(m.group(4)) * 60 + int(m.group(5))


def legacy(d, mins):
    """The retired gate: after 15:30 or a non-trading day -> next trading day (gate_calendar)."""
    if mins > 15 * 60 + 30 or d not in CALSET:
        i = bisect.bisect_right(CAL, d)
        return CAL[i] if i < len(CAL) else d
    return d


def dt(d):
    return datetime.date(d // 10000, d // 100 % 100, d % 100)


def rewrite_shp(path, apply):
    L = json.load(open(path, encoding="utf-8"))
    c = collections.Counter()
    samples = collections.defaultdict(list)
    for k, e in L.items():
        if k.startswith("_") or not isinstance(e, dict):
            continue
        d, mins = parse_ts(e.get("ts"))
        if d is None:
            c["no_ts"] += 1
            continue
        sub = e.get("sub")
        if not isinstance(sub, int):
            c["no_int_sub"] += 1
            continue
        if e.get("rule") == RULE or sub == d:
            c["already_raw"] += 1
            continue
        # The gate's form under TODAY's calendar, or — for an entry the campaigns tagged gated_1530 — any date
        # 1-4 days after the broadcast day (the Aug-23 pass ran on a calendar that still carried spurious
        # weekend bars, so some of its "next trading day" stamps land on a Sunday; same filing, same rule).
        # A §142i repair entry records the BSE timestamp in `ts` but gated the NSE broadcast day it found in
        # `was` (sub = was + 1-2 days over a weekend, ts LATER than both): there the raw day is `was`.
        target = None
        if sub == legacy(d, mins) or (e.get("gated_1530") and 0 < (dt(sub) - dt(d)).days <= 4):
            target = d
        elif e.get("gated_1530") and isinstance(e.get("was"), int) and 0 < (dt(sub) - dt(e["was"])).days <= 4:
            target = e["was"]
            c["rewritten_to_was"] += 1
        if target is not None:
            c["rewritten"] += 1
            if len(samples["rewritten"]) < 3:
                samples["rewritten"].append((k, sub, "->", target))
            if apply:
                e["sub_1530"] = sub
                e["sub"] = target
                e["rule"] = RULE
                if "days_later" in e and isinstance(e.get("was"), int):
                    e["days_later"] = (dt(target) - dt(e["was"])).days
        else:
            c["anomaly_untouched"] += 1
            if len(samples["anomaly"]) < 4:
                samples["anomaly"].append((k, {x: e.get(x) for x in ("sub", "was", "ts", "src", "prov")}))
    print(f"{os.path.basename(path)}: {dict(c)}")
    for kind, s in samples.items():
        for x in s:
            print("   ", kind, x)
    if apply:
        json.dump(L, open(path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    return c["rewritten"]


# A reviewer's note links the BSE timestamp to the date it stamped with an arrow, in a few spellings:
#   "NEWS_DT 2018-05-28T20:46:06.323 -> gated 20180529"      "Sat 2022-11-12T12:55 -> Mon 20221114"
#   "2025-05-29T16:49 post-close -> 2025-05-30"              — timestamp, ≤60 chars, "->", optional word, date
EXACT_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})[^\n]{0,60}?->\s*(?:[A-Za-z]+\s+)?(\d{4})-?(\d{2})-?(\d{2})\b")


def month_end_evidence():
    """(stored date -> month-end it would have been pushed from, by_id, BSE times cache) — the same evidence
    ungate_1530.py uses. Lets an `exact` entry whose note has no arrow form still be un-gated when it sits on
    the day after a month-end and BSE shows that scrip's Result broadcasts on the month-end were all after close."""
    import gzip

    cal = json.load(open(os.path.join(HERE, "gate_calendar.json")))
    tdl = sorted(cal["tdays"])
    after = {}
    for me in cal["me_days"]:
        i = bisect.bisect_right(tdl, me)
        if i < len(tdl):
            after[tdl[i]] = me
        x = dt(me) + datetime.timedelta(days=1)
        while x.weekday() >= 5:
            x += datetime.timedelta(days=1)
        after.setdefault(x.year * 10000 + x.month * 100 + x.day, me)
    by_id = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    times = json.load(gzip.open(os.path.join(HERE, "filing_times_cache.json.gz")))
    return after, by_id, times


def rewrite_ann_fills(path, apply):
    D = json.load(open(path, encoding="utf-8"))
    c = collections.Counter()
    samples = collections.defaultdict(list)
    after, by_id, times = month_end_evidence()
    for k, e in D.items():
        if k.startswith("_") or not isinstance(e, dict) or not e.get("exact"):
            continue
        ann = e.get("ann")
        if e.get("rule") == RULE:
            c["already"] += 1
            continue
        hits = [(ts, int(y + m + dd)) for ts, y, m, dd in EXACT_RE.findall(json.dumps(e, ensure_ascii=False))]
        mine = [ts for ts, g in hits if g == ann]
        if not mine:
            # Pass 2 — no arrow in the note: use the month-end BSE evidence (only the month-end class can
            # change a monthly backtest; a gated non-month-end exact date is a one-day-late visibility).
            me = after.get(ann)
            sc = by_id.get(k.split("|")[0])
            tl = (times.get(str(me), {}) or {}).get(str(sc)) if me and sc is not None else None
            mm = [m for m in (parse_ts(t)[1] for t in (tl or [])) if m is not None]
            if mm and min(mm) > 15 * 60 + 30:
                c["rewritten_by_bse_cache"] += 1
                c["rewritten"] += 1
                if len(samples["rewritten_cache"]) < 3:
                    samples["rewritten_cache"].append((k, ann, "->", me))
                if apply:
                    e["ann_1530"] = ann
                    e["ann"] = me
                    e["rule"] = RULE
                    e["evidence_1530"] = "BSE Result broadcasts on %d all after 15:30 (filing_times_cache)" % me
                continue
            c["no_arrow_in_note_left_as_is" if not hits else "note_ts_for_other_date_left_as_is"] += 1
            if len(samples["unmatched"]) < 3:
                samples["unmatched"].append((k, ann, str(e.get("src"))[:160]))
            continue
        d, mins = parse_ts(mine[0])
        if d == ann:
            c["already_raw"] += 1
            continue
        if legacy(d, mins) == ann or 0 < (dt(ann) - dt(d)).days <= 4:
            c["rewritten"] += 1
            if len(samples["rewritten"]) < 3:
                samples["rewritten"].append((k, ann, "->", d))
            if apply:
                e["ann_1530"] = ann
                e["ann"] = d
                e["rule"] = RULE
        else:
            c["anomaly_untouched"] += 1
            if len(samples["anomaly"]) < 3:
                samples["anomaly"].append((k, ann, mine[0]))
    print(f"{os.path.basename(path)} (exact entries): {dict(c)}")
    for kind, s in samples.items():
        for x in s:
            print("   ", kind, x)
    if apply:
        json.dump(D, open(path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    return c["rewritten"]


def rewrite_bse_fills(path, apply):
    L = json.load(open(path, encoding="utf-8"))
    c = collections.Counter()
    for e in L:
        d, _mins = parse_ts(e.get("filed"))
        ann = e.get("ann")
        if d is None or not isinstance(ann, int):
            c["no_ts"] += 1
            continue
        if ann == d:
            c["already_raw"] += 1
            continue
        c["rewritten"] += 1
        print("    bse_result_fills", e.get("sym"), e.get("qe"), ann, "->", d)
        if apply:
            e["ann_1530"] = ann
            e["ann"] = d
            e["rule"] = RULE
    print(f"{os.path.basename(path)}: {dict(c)}")
    if apply:
        json.dump(L, open(path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    return c["rewritten"]


def main():
    apply = "--apply" in sys.argv
    n = 0
    n += rewrite_shp(os.path.join(HERE, "shp_lag_fix.json"), apply)
    n += rewrite_shp(os.path.join(HERE, "shp_sub_dates.json"), apply)
    n += rewrite_ann_fills(os.path.join(HERE, "ann_date_fills.json"), apply)
    n += rewrite_bse_fills(os.path.join(HERE, "bse_result_fills.json"), apply)
    cf = json.load(open(os.path.join(HERE, "ann_cell_fix.json"), encoding="utf-8")).get("fixes", [])
    for e in cf:
        print(
            "ann_cell_fix.json (hand-check):",
            e.get("sym"),
            e.get("qe"),
            "fixed",
            e.get("fixed"),
            "|",
            str(e.get("why"))[:200],
        )
    print(("APPLIED" if apply else "DRY RUN — would rewrite") + f" {n} ledger entries")


if __name__ == "__main__":
    main()
