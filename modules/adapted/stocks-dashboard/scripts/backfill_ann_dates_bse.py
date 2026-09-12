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
"""Recover REAL declared dates for ann=0 (date-unknown sentinel) result rows from the BSE
announcement archive — metadata only, no PDFs, no vision, no API key.

The ann=0 rows (mostly BSE-PDF profit backfills that never captured the filing date) are
invisible to point-in-time screens/backtests: the quarter's number exists but the backtest
never learns WHEN the market saw it, so it skips the quarter. BSE's announcement archive
stamps every results filing with its exact date — this recovers genuine dates, never guesses:

  1. TARGETS  — every (sym, qe) in docs/sf_fundamentals.json with PAT present and ann==0.
  2. FETCH    — BSE announcements for the scrip in (qe+1 .. qe+150d) via fetch_insurers.datebound
                (result filings only, all categories, paginated).
  3. MATCH    — a filing whose NEWSSUB states the period (fetch_announcements.parse_qe) equal to
                the target qe wins (earliest such date = first declaration; audited refilings lose).
                Fallback: if NO filing states a period but the window holds exactly ONE distinct
                result-filing date inside (qe+5d .. qe+100d), that solo date is accepted ("solo").
                Anything else -> skip with reason (ambiguous / no-candidates / no-scrip).
  4. APPLY    — ledger scripts/ann_date_fills.json, then fill-only (current ann==0, PAT present)
                into BOTH docs/sf_fundamentals.json and scripts/fundamentals.json (master mirror —
                runbook: heal both or the nightly resurrects the 0). NEVER writes ann <= qe
                (impossible-pair rule) — window start makes that structurally true, checked anyway.

Resumable: fills ledger + scripts/_ann_date_skips.json are consulted on rerun. A burst of
consecutive empty windows = BSE rate-limit stub (162-byte-bse.json lesson) -> abort, nothing
recorded for the burst, rerun later.

Run:
  python -X utf8 scripts/backfill_ann_dates_bse.py --limit 30      # trial
  python -X utf8 scripts/backfill_ann_dates_bse.py                 # full sweep
  python -X utf8 scripts/backfill_ann_dates_bse.py --reapply       # ledger -> files, no fetching
  python -X utf8 scripts/backfill_ann_dates_bse.py --retry-skips   # re-attempt skipped keys
"""
import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bse_resolve as BR  # ISIN guard on symbol->scrip (runbook §76)
import fetch_insurers as FI  # _opener/bse_get/datebound — proven BSE helpers
from fetch_announcements import parse_qe  # anchored period parser (runbook §15)

SF = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MASTER = os.path.join(HERE, "fundamentals.json")
LEDGER = os.path.join(HERE, "ann_date_fills.json")
SKIPS = os.path.join(HERE, "_ann_date_skips.json")


def jload(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def jsave(p, obj):
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
    os.replace(tmp, p)


def qe_date(qe):
    return datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)


def plus(qe, days):
    return int((qe_date(qe) + datetime.timedelta(days=days)).strftime("%Y%m%d"))


def scrip_map():
    # ISIN-GUARDED (§76). Both sources key on a BSE-side label that can collide with an NSE
    # ticker: by_id is BSE's scrip_id, and bse_universe rows carry the same scrip_id in r[1].
    # Cleaning by_id alone is NOT enough here — the universe fallback would re-supply the wrong
    # code (that is exactly how KALYANI would have picked Kalyani Cast-Tech's announce dates).
    m = dict((jload(os.path.join(HERE, "bse_scrips.json"), {}) or {}).get("by_id") or {})
    for r in (jload(os.path.join(ROOT, "docs", "bse_universe.json"), {}) or {}).get("rows") or []:
        m.setdefault(str(r[1]).upper(), r[0])
    # DELISTED/merged names: both sources above come from BSE's ACTIVE-equity scrape, so a company
    # that has since merged or delisted is in neither, and every one of its quarters skips as
    # "no-scrip" — a missing IDENTITY, not a missing filing. bse_scrips_delisted.json carries those
    # codes, each gated on an EXACT ISIN match against BSE's all-status master. setdefault, so a
    # live answer always wins; guard_map below still has the final say (§76).
    for sym, e in ((jload(os.path.join(HERE, "bse_scrips_delisted.json"), {}) or {}).get("scrips") or {}).items():
        if e.get("bse_code"):
            m.setdefault(str(sym).upper(), str(e["bse_code"]))
    return BR.guard_map(m)


def targets(fund):
    out = []
    for sym, arr in fund.items():
        for q in arr:
            if not (isinstance(q, list) and len(q) >= 5 and isinstance(q[0], int)):
                continue
            if (q[1] is not None and q[2] == 0) or (q[3] is not None and q[4] == 0):
                out.append((sym, q[0]))
    return sorted(out)


def q_neighbors(qe):
    y, md = qe // 10000, qe % 10000
    prv = {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}[md]
    nxt = {331: y * 10000 + 630, 630: y * 10000 + 930, 930: y * 10000 + 1231, 1231: (y + 1) * 10000 + 331}[md]
    return prv, nxt


def resolve(cands, qe, prev_ann=None, next_ann=None):
    """cands = [(ann_int, attachment, newssub), ...] -> (ann, how) or (None, reason).
    prev_ann/next_ann = KNOWN declared dates of the neighbouring quarters (bounds for the
    second-pass "seq" rule: the target's declaration must sit strictly between them)."""
    cands = [c for c in cands if c[0] > qe]  # impossible-pair rule, belt
    if not cands:
        return None, "no-candidates"
    parsed = [(c[0], parse_qe(c[2])) for c in cands]
    exact = [d for d, pq in parsed if pq == qe]
    if exact:
        return min(exact), "exact"
    stated = [(d, pq) for d, pq in parsed if pq not in (0, qe)]  # states a DIFFERENT period
    stated_dates = {d for d, _ in stated}  # same-day twin = same board
    later_min = min([d for d, pq in stated if pq > qe], default=None)
    unstated = sorted({d for d, pq in parsed if pq == 0})
    hi = plus(qe, 150) if next_ann else plus(qe, 100)
    ok = [
        d
        for d in unstated
        if plus(qe, 5) <= d <= hi
        and d not in stated_dates
        and (not prev_ann or d > prev_ann)
        and (not next_ann or d < next_ann)
        and (later_min is None or d < later_min)
    ]
    if not ok:
        if stated:
            return None, "other-period:{}".format(",".join(str(pq) for pq in sorted({p for _, p in stated})))
        return None, ("ambiguous:%d-dates" % len(unstated)) if unstated else "outside-band"
    if len(ok) == 1:
        return ok[0], "seq" if (stated or next_ann) else "solo"
    if next_ann or later_min:  # bounded above by a KNOWN later declaration -> earliest wins
        return ok[0], "seq"
    return None, "ambiguous:%d-dates" % len(ok)


def apply_ledger(ledger):
    """Ledger -> both fundamentals files. Returns (cells_docs, cells_master).

    Three entry kinds:
      normal              — FILL-ONLY (current ann==0, PAT present). Unchanged historic behavior.
      "override": true    — CORRECTS a wrong-LATE date: applied when the stored ann is a real date
                            LATER than the ledger's. Only ever moves a date EARLIER (toward the
                            true first-public date, never later) — the NSE-broadcast-lag class
                            (SBICARD 88d / MFSL 61d / DHANI 22d / ABB 118d...; runbook §104).
                            This is what makes the heals REBUILD-PROOF: a full rebuild resurrects
                            NSE's lagged dates, and the nightly --reapply re-asserts the truth.
      "exact": true       — hand-adjudicated PIT-EFFECTIVE date, asserted in BOTH directions
                            (a populated ann that differs is set to it, earlier or later).
                            For the wrong-EARLY (look-ahead) class the override kind cannot
                            express: a stored date that PRECEDES the true first-public filing
                            (SUZLON Mar-2020: a tier-2 seq override matched a debt-restructuring
                            board outcome, 80 days before the results; TASTYBITE Mar-2021 /
                            NMDC Jun-2019: the board-meeting INTIMATION stamped as the result
                            date). Unlike raw-BSE override dates, an exact date is the GATED
                            (15:30/weekend-aware, runbook §12) value — write the date the engine
                            should compare against, so no buffer applies. Reviewed entries only:
                            each needs the BSE announcement timestamp in its src note."""
    counts = []
    for path in (SF, MASTER):
        data = jload(path, None)
        if data is None:
            print("WARN missing", path)
            counts.append(0)
            continue
        n = 0
        for key, rec in ledger.items():
            sym, qe = key.split("|")
            qe = int(qe)
            ann = int(rec["ann"])
            if ann <= qe:  # never store an impossible pair
                continue
            ovr = bool(rec.get("override"))
            for q in data.get(sym) or []:
                if not (isinstance(q, list) and len(q) >= 5 and q[0] == qe):
                    continue
                if rec.get("exact"):  # adjudicated PIT date — asserted both ways, no gate buffer
                    if q[1] is not None and isinstance(q[2], int) and q[2] > 0 and q[2] != ann:
                        q[2] = ann
                        n += 1
                    if q[3] is not None and isinstance(q[4], int) and q[4] > 0 and q[4] != ann:
                        q[4] = ann
                        n += 1
                    continue
                if q[1] is not None and q[2] == 0:
                    q[2] = ann
                    n += 1
                if q[3] is not None and q[4] == 0:
                    q[4] = ann
                    n += 1
                if ovr:  # earlier-only correction of populated dates.
                    # GATE BUFFER (adjudicated 2026-08-23): ledger dates here are RAW BSE filing
                    # dates, but the engine's PIT convention gates post-15:30/weekend/holiday
                    # filings to the next trading day (runbook §12) — up to +4 calendar days
                    # (Fri evening + Mon holiday). A stored date within [ann, ann+4] is the GATED
                    # form of the same event, not a lag: overriding it re-introduces a half-day
                    # look-ahead and ping-pongs with the nightly gate_1530 pass. Only a stored
                    # date > ann+4 is a genuine NSE-broadcast-lag.
                    if q[1] is not None and isinstance(q[2], int) and q[2] > plus(ann, 4):
                        q[2] = ann
                        n += 1
                    if q[3] is not None and isinstance(q[4], int) and q[4] > plus(ann, 4):
                        q[4] = ann
                        n += 1
        if n:
            jsave(path, data)
        counts.append(n)
        print("applied %d cells -> %s" % (n, os.path.normpath(path)))
    return counts


RSKIPS = os.path.join(HERE, "_ann_recon_skips.json")


def reconcile_recent(ledger, args):
    """§104 go-forward guard for the NSE-broadcast-lag class: for DATED cells in the actively-
    filing window (qe within --recent days of today), resolve the true first-public date from the
    BSE announcement archive; where it precedes the stored date by >4 days (beyond the 15:30/
    weekend/holiday gate window), ledger an override
    (earlier-only) and apply. Bounded (--limit/--max-minutes), resumable (skips keyed on the
    stored date, so a cell is re-checked if its stored date ever changes), rate-limit aware."""
    skips = jload(RSKIPS, {})
    fund = jload(SF, {})
    codes = scrip_map()
    today = int(datetime.date.today().strftime("%Y%m%d"))
    floor = int((datetime.date.today() - datetime.timedelta(days=args.recent)).strftime("%Y%m%d"))
    todo = []
    for sym, arr in fund.items():
        for q in arr:
            if not (isinstance(q, list) and len(q) >= 5 and isinstance(q[0], int)):
                continue
            if q[0] < floor:
                continue
            stored = min([a for a in (q[2], q[4]) if isinstance(a, int) and a > 0], default=None)
            if stored is None:  # undated cells are the FILL flow's job, not ours
                continue
            key = "%s|%d|%d" % (sym, q[0], stored)  # stored date in the key -> re-check on change
            if key in skips or "%s|%d" % (sym, q[0]) in ledger:
                continue
            todo.append((sym, q[0], stored, key))
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",")}
        todo = [t for t in todo if t[0] in only]
    todo.sort()
    if args.limit:
        todo = todo[: args.limit]
    print("reconcile targets: %d dated cells (qe >= %d)" % (len(todo), floor))
    known = {}
    for sym, arr in fund.items():
        for q in arr:
            if isinstance(q, list) and len(q) >= 5 and isinstance(q[0], int):
                ann = min([a for a in (q[2], q[4]) if a], default=None)
                if ann:
                    known[(sym, q[0])] = ann
    o = FI.bse_session()
    t0 = time.time()
    done = corrected = 0
    empty_streak = 0
    streak_keys = []
    for sym, qe, stored, key in todo:
        if args.max_minutes and (time.time() - t0) / 60 > args.max_minutes:
            print("time budget reached — stopping (resumable)")
            break
        code = codes.get(sym)
        if not code:
            skips[key] = "no-scrip"
            done += 1
            continue
        try:
            cands = FI.datebound(o, code, str(plus(qe, 1)), str(min(plus(qe, 240), today)))
        except Exception as ex:
            print(f"  {key} fetch err: {str(ex)[:80]}")
            cands = []
        if not cands:
            empty_streak += 1
            streak_keys.append(key)
        else:
            empty_streak = 0
            streak_keys = []
        if empty_streak >= 8:
            for k in streak_keys:
                skips.pop(k, None)
            print(
                "8 consecutive empty windows — BSE likely rate-limiting; aborting run (burst not recorded), rerun later"
            )
            break
        prv, nxt = q_neighbors(qe)
        ann, how = resolve(cands, qe, known.get((sym, prv)), known.get((sym, nxt)))
        if (
            ann and ann > qe and (qe_date(stored) - qe_date(ann)).days > 4
        ):  # >4d: beyond the 15:30/weekend/holiday gate window (runbook 12) — smaller deltas are the GATED form of the same filing, not a lag
            ledger["%s|%d" % (sym, qe)] = {"ann": ann, "src": "bse:recon:" + how, "override": True, "was": stored}
            corrected += 1
            print(
                "  %-14s %d  stored=%d -> bse=%d (%s, %dd earlier)"
                % (sym, qe, stored, ann, how, (qe_date(stored) - qe_date(ann)).days)
            )
        else:
            skips[key] = "ok:%s" % (how if not ann else "match")
        done += 1
        if done % 25 == 0:
            jsave(LEDGER, ledger)
            jsave(RSKIPS, skips)
            print("… %d/%d checked, %d corrections" % (done, len(todo), corrected))
        time.sleep(0.6)
    jsave(LEDGER, ledger)
    jsave(RSKIPS, skips)
    print("reconciled: %d checked, %d lagged dates corrected" % (done, corrected))
    if corrected:
        apply_ledger(ledger)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max (sym,qe) rows to fetch this run")
    ap.add_argument("--only", default="", help="comma-separated symbols")
    ap.add_argument("--reapply", action="store_true", help="apply ledger to files, no fetching")
    ap.add_argument("--retry-skips", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=0)
    ap.add_argument(
        "--recent",
        type=int,
        default=0,
        metavar="DAYS",
        help="RECONCILE mode (runbook §104): re-check DATED cells whose qe is within "
        "DAYS of today against the BSE archive; where BSE's first-public date is "
        "EARLIER than the stored (NSE-broadcast) date by >4 days (past the 15:30 "
        "gate window), write an "
        "override ledger entry and apply. Stops the NSE-lag class regrowing.",
    )
    args = ap.parse_args()

    ledger = jload(LEDGER, {})
    if args.reapply:
        apply_ledger(ledger)
        return
    if args.recent:
        reconcile_recent(ledger, args)
        return

    skips = jload(SKIPS, {})
    fund = jload(SF, {})
    codes = scrip_map()
    todo = targets(fund)
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",")}
        todo = [t for t in todo if t[0] in only]
    todo = [t for t in todo if "%s|%d" % t not in ledger and (args.retry_skips or "%s|%d" % t not in skips)]
    if args.limit:
        todo = todo[: args.limit]
    print("targets: %d rows across %d companies" % (len(todo), len({s for s, _ in todo})))

    known = {}  # (sym, qe) -> known declared date (bounds)
    for sym, arr in fund.items():
        for q in arr:
            if isinstance(q, list) and len(q) >= 5 and isinstance(q[0], int):
                ann = min([a for a in (q[2], q[4]) if a], default=None)
                if ann:
                    known[(sym, q[0])] = ann

    o = FI.bse_session()
    t0 = time.time()
    done = filled = 0
    empty_streak = 0
    streak_keys = []
    for sym, qe in todo:
        if args.max_minutes and (time.time() - t0) / 60 > args.max_minutes:
            print("time budget reached — stopping (resumable)")
            break
        key = "%s|%d" % (sym, qe)
        code = codes.get(sym)
        if not code:
            skips[key] = "no-scrip"
            done += 1
            continue
        try:
            cands = FI.datebound(o, code, str(plus(qe, 1)), str(plus(qe, 240)))
        except Exception as ex:
            print(f"  {key} fetch err: {str(ex)[:80]}")
            cands = []
        if not cands:
            empty_streak += 1
            streak_keys.append(key)
        else:
            empty_streak = 0
            streak_keys = []
        if empty_streak >= 8:
            for k in streak_keys:  # a burst of empties = rate-limit stub, not truth
                skips.pop(k, None)
            print(
                "8 consecutive empty windows — BSE likely rate-limiting; aborting run (burst not recorded), rerun later"
            )
            break
        prv, nxt = q_neighbors(qe)
        ann, how = resolve(cands, qe, known.get((sym, prv)), known.get((sym, nxt)))
        if ann:
            ledger[key] = {"ann": ann, "src": "bse:" + how}
            known[(sym, qe)] = ann  # TODO is qe-ascending: a fill bounds the same co's later targets
            filled += 1
            print("  %-14s %d -> %d (%s)" % (sym, qe, ann, how))
        elif cands or how == "no-candidates":
            skips[key] = how
        done += 1
        if done % 25 == 0:
            jsave(LEDGER, ledger)
            jsave(SKIPS, skips)
            print("… %d/%d done, %d filled" % (done, len(todo), filled))
        time.sleep(0.6)

    jsave(LEDGER, ledger)
    jsave(SKIPS, skips)
    print("fetched: %d rows, %d dates recovered, %d skipped-this-run" % (done, filled, done - filled))
    if filled:
        apply_ledger(ledger)


if __name__ == "__main__":
    main()
