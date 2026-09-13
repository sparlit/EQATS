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
"""Floor the freshly fetched price series against what we already published.

DATA_RUNBOOK.md section 1b. Runs between fetch_all.py and build_compressed.py.

WHY THIS EXISTS
fetch_all.py rebuilds scripts/stock_data.json from scratch on every run — there is no
merge with the previous build, so whatever Yahoo happens to return IS what ships. Yahoo
intermittently serves a series with one whole session missing, and it is not the same
session every time: measured 2026-08-19 over the last 40 published dash_slim.bin builds,
17 builds shipped a session collapsed to 10-27% of its real bar count (2026-07-31 went
4454 -> 598 bars between two builds 1h45m apart, then back to 4647 the next morning).
guard_feed.py could not see it: dropping 3,856 whole bars costs 0.55% of the gzip stream,
far inside its 90%-of-previous-size floor.

WHAT IT DOES  (both passes are FILL-ONLY — a date the fresh fetch has is never overwritten,
so a genuine Yahoo close correction still wins)
  1. FLOOR PASS  — re-adds bars present in the committed docs/dash_slim.bin but missing from
     the fresh fetch. A bar published yesterday can no longer vanish today.
  2. LEDGER PASS — applies scripts/price_gap_fills.json, the recorded heal for sessions that
     were already lost before the floor pass existed (CLAUDE.md rule 5: heal via a ledger,
     never by editing the derived file).

BASIS ANCHORS. Yahoo re-adjusts a whole series retroactively for a split/bonus, so a close
recovered from an older build can be on a stale basis. Every re-added bar is gated on the
ticker's NEIGHBOURING closes still matching between the two sources; a mismatch means the
series was re-adjusted and the bar is skipped and counted, never rescaled by guesswork.
"""
import datetime as dt
import gzip
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRESH = os.path.join(ROOT, "scripts", "stock_data.json")
SLIM = os.path.join(ROOT, "docs", "dash_slim.bin")
LEDGER = os.path.join(ROOT, "scripts", "price_gap_fills.json")

DAY = 86400
NEIGH = 6  # shared sessions either side that must agree to prove the same basis
MIN_ANCHORS = 3


def paise(close):
    return round(close * 100)


def main():
    with open(FRESH, encoding="utf-8") as fh:
        payload = json.load(fh)
    start_ts = payload["startTs"]
    series = payload["series"]

    def off(ts):
        return int((ts - start_ts) // DAY)

    def off2date(o):
        return dt.datetime.fromtimestamp(start_ts + o * DAY, dt.UTC).date().isoformat()

    # Per-ticker offset -> close, and the canonical timestamp each session carries in THIS
    # payload. A re-added bar is stamped with the session ts its peers already use, so it
    # buckets to the same day build_compressed.py will bucket them to.
    fresh = {}
    ts_votes = {}
    for tkr, pairs in series.items():
        m = {}
        for ts, close in pairs:
            o = off(ts)
            m[o] = close
            ts_votes.setdefault(o, Counter())[ts] += 1
        fresh[tkr] = m
    off2ts = {o: c.most_common(1)[0][0] for o, c in ts_votes.items()}
    date2off = {off2date(o): o for o in off2ts}
    newest = max(off2ts) if off2ts else None
    added = {}  # tkr -> {off: close}
    stat = Counter()

    def basis_ok(mine, theirs, o):
        """Do the two sources agree on the NEIGH closest shared sessions around `o`?"""
        shared = sorted((x for x in theirs if x in mine), key=lambda x: abs(x - o))[:NEIGH]
        if len(shared) < MIN_ANCHORS:
            stat["skip_too_few_anchors"] += 1
            return False
        if any(paise(mine[x]) != theirs[x] for x in shared):
            stat["skip_basis_mismatch"] += 1
            return False
        return True

    # ---- pass 1: floor against the committed dash_slim.bin -------------------------------
    if newest is None:
        print("heal: fresh payload has no bars at all — nothing to floor against", flush=True)
    elif not os.path.exists(SLIM):
        print(f"heal: {SLIM} missing — FLOOR PASS SKIPPED (first build?)", flush=True)
    else:
        try:
            slim = json.loads(gzip.decompress(open(SLIM, "rb").read()))
        except Exception as exc:
            slim = None
            print(f"heal: could not read committed dash_slim.bin ({exc}) — FLOOR PASS SKIPPED", flush=True)
        if slim is not None and slim.get("startTs") != start_ts:
            print(
                f"heal: committed dash_slim startTs={slim.get('startTs')} != fresh {start_ts} "
                "— FLOOR PASS SKIPPED (offsets would not align)",
                flush=True,
            )
        elif slim is not None:
            for tkr, cs in slim["series"].items():
                mine = fresh.get(tkr)
                if not mine:
                    stat["ticker_absent_from_fetch"] += 1
                    continue
                theirs = dict(zip(cs["d"], cs["p"], strict=False))
                floor_from = min(mine)
                gaps = [o for o in theirs if o not in mine and floor_from <= o < newest]
                for o in gaps:
                    if o not in off2ts:
                        stat["skip_no_session_ts"] += 1
                        continue
                    if not basis_ok(mine, theirs, o):
                        continue
                    added.setdefault(tkr, {})[o] = round(theirs[o] / 100, 2)
                    stat["floor_restored"] += 1

    # ---- pass 2: the recorded heal ledger ------------------------------------------------
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as fh:
            fills = json.load(fh).get("fills", {})
        for tkr, rows in fills.items():
            mine = fresh.get(tkr)
            if not mine:
                stat["ledger_ticker_absent"] += 1
                continue
            for date, close, pdate, pclose, ndate, nclose in rows:
                o = date2off.get(date)
                if o is None:
                    stat["ledger_no_such_session"] += 1
                    continue
                if o in mine or o in added.get(tkr, {}):
                    stat["ledger_already_present"] += 1
                    continue
                # anchors: at least one must still match, none may contradict
                hits = 0
                bad = False
                for adate, aclose in ((pdate, pclose), (ndate, nclose)):
                    ao = date2off.get(adate)
                    if not adate or ao is None or ao not in mine:
                        continue
                    if paise(mine[ao]) == paise(aclose):
                        hits += 1
                    else:
                        bad = True
                if bad or hits == 0:
                    stat["ledger_anchor_failed"] += 1
                    continue
                if o not in off2ts:
                    stat["ledger_no_session_ts"] += 1
                    continue
                added.setdefault(tkr, {})[o] = close
                stat["ledger_filled"] += 1
    else:
        print(f"heal: no ledger at {LEDGER} — LEDGER PASS SKIPPED", flush=True)

    # ---- splice back, keeping each series sorted + deduped by ts --------------------------
    per_session = Counter()
    for tkr, bars in added.items():
        merged = dict(series[tkr])
        for o, close in bars.items():
            merged[off2ts[o]] = close
            per_session[o] += 1
        series[tkr] = [[ts, merged[ts]] for ts in sorted(merged)]

    total = sum(len(v) for v in added.values())
    print(
        f"heal: restored {total} bars across {len(added)} tickers "
        f"(floor={stat['floor_restored']}, ledger={stat['ledger_filled']})",
        flush=True,
    )
    for key in sorted(k for k in stat if k.startswith(("skip_", "ledger_", "ticker_"))):
        if stat[key] and key != "ledger_filled":
            print(f"       {key}: {stat[key]}", flush=True)
    if per_session:
        print("       per session (bars re-added):", flush=True)
        for o in sorted(per_session):
            print(f"         {off2date(o)}  +{per_session[o]}", flush=True)

    if total:
        with open(FRESH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        print(f"heal: rewrote {FRESH}", flush=True)
    else:
        print("heal: nothing to restore — file untouched", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
