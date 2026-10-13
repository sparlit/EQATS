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

WHAT IT DOES  (the two fill passes are FILL-ONLY — a date the fresh fetch has is never overwritten,
so a genuine Yahoo close correction still wins)
  0. PHANTOM PASS — drops a "session" on a day no exchange traded. Yahoo pads exchange holidays
     with a flat bar (open == close == the previous close, volume 0) for ~1,400-1,800 tickers:
     2026-01-15, 2026-05-01, and 2026-09-14 (Ganesh Chaturthi — ^NSEI has no bar, NSE re-served
     the 09-11 file, BSE published nothing). A phantom that appears while its date is still the
     newest session is exempt in guard_sessions.py and slips into the committed copy (the first
     two, now standing WARNs); one that appears AFTER the store has moved on (09-14 surfaced on
     09-15, with the store frozen at 09-11) reads as new damage at 30% of the median and blocked
     every refresh for three days. Two independent tests must both hold before a drop: the
     exchange calendar says closed (scripts/fo_spot_nse.json `_holidays` — dates NSE published
     no F&O bhavcopy for) AND >= CARRY_FLOOR of the session's bars repeat the ticker's previous
     close to the paisa (real sessions 11-13%, phantoms 100%). Holiday-listed but prices moved →
     kept and reported. DATA_RUNBOOK 1b-iii.
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
HOLIDAYS = os.path.join(
    ROOT, "scripts", "fo_spot_nse.json"
)  # "_holidays": no F&O bhavcopy = exchange closed
CARRY_FLOOR = 0.90  # phantom signature: share of a session's bars that repeat the previous close
MIN_PHANTOM_BARS = (
    100  # below this the carry-forward share is noise (lone pre-2020 weekly bars) — leave alone
)


def paise(close):
    return int(round(close * 100))


def main():
    with open(FRESH, encoding="utf-8") as fh:
        payload = json.load(fh)
    start_ts = payload["startTs"]
    series = payload["series"]
    # Nifty 500 members whose Yahoo series fill_prices_from_sf.py REPLACED with the NSE-bhavcopy store
    # (§214a F1). The floor and ledger passes below re-add bars from the last published build / the Yahoo
    # gap ledger — Yahoo-basis closes — so they skip these rows (one source per ticker). The phantom pass
    # still applies: it only drops, and a Yahoo tail bar on an exchange holiday is exactly its case.
    replaced = {
        t
        for t, m in (payload.get("meta") or {}).items()
        if (m or {}).get("srcFrom") == "yahoo-replaced"
    }

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
    added = {}  # tkr -> {off: close}
    stat = Counter()

    # ---- pass 0: drop phantom sessions (exchange holidays Yahoo pads with flat bars) ------------
    # Both tests must hold (see module docstring): the exchange calendar says closed, AND the
    # session's bars overwhelmingly repeat each ticker's previous close. Runs BEFORE the floor
    # pass and removes the offset from off2ts, so a phantom the committed copy already carries
    # is not floored back in (skip_no_session_ts) — the two legacy WARN sessions purge themselves.
    holidays = set()
    if os.path.exists(HOLIDAYS):
        try:
            with open(HOLIDAYS, encoding="utf-8") as fh:
                holidays = set(json.load(fh).get("_holidays") or [])
        except Exception as exc:  # noqa: BLE001
            print(f"heal: could not read {HOLIDAYS} ({exc}) — PHANTOM PASS SKIPPED", flush=True)
    dropped = {}  # date -> bars removed
    for o in sorted(off2ts):
        date = off2date(o)
        if date not in holidays:
            continue
        n = same = 0
        for mine in fresh.values():
            if o not in mine:
                continue
            n += 1
            prev = max((x for x in mine if x < o), default=None)
            if prev is not None and paise(mine[prev]) == paise(mine[o]):
                same += 1
        if n < MIN_PHANTOM_BARS:
            continue
        frac = same / n
        if frac < CARRY_FLOOR:
            print(
                f"heal: WARN {date} is holiday-listed but only {frac:.0%} of its {n} bars repeat the "
                f"prior close (floor {CARRY_FLOOR:.0%}) — kept; check the calendar (special session?)",
                flush=True,
            )
            continue
        for tkr, mine in fresh.items():
            if o in mine:
                del mine[o]
                series[tkr] = [[ts, c] for ts, c in series[tkr] if off(ts) != o]
        del off2ts[o]
        dropped[date] = n
        print(
            f"heal: PHANTOM session {date} dropped — exchange holiday and {frac:.0%} of its {n} bars "
            f"repeat the prior close",
            flush=True,
        )
    date2off = {off2date(o): o for o in off2ts}
    newest = max(off2ts) if off2ts else None

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
        except Exception as exc:  # noqa: BLE001
            slim = None
            print(
                f"heal: could not read committed dash_slim.bin ({exc}) — FLOOR PASS SKIPPED",
                flush=True,
            )
        if slim is not None and slim.get("startTs") != start_ts:
            print(
                f"heal: committed dash_slim startTs={slim.get('startTs')} != fresh {start_ts} "
                "— FLOOR PASS SKIPPED (offsets would not align)",
                flush=True,
            )
        elif slim is not None:
            # The committed copy's NEWEST session was still filling when it was committed
            # (refresh.yml runs 3-4x through the close; the 15:30 IST snapshot carries
            # last-traded prices, not the official closes). It may be floored like any other
            # bar, but it is NOT a basis anchor: on 2026-09-08 Yahoo wiped 2026-09-07 (an
            # all-null bar) for ~1,650 tickers and 834 re-adds were refused as "basis
            # mismatch" only because the nearest shared session was the intraday 09-08
            # snapshot, which differs from the final close by design — the guard then
            # blocked every refresh for two days. Anchors come from sessions that were
            # complete when committed. DATA_RUNBOOK 1b (2026-09-09).
            slim_newest = max(
                (max(cs["d"]) for cs in slim["series"].values() if cs["d"]), default=None
            )
            for tkr, cs in slim["series"].items():
                if tkr in replaced:
                    stat["skip_replaced_by_store"] += 1
                    continue
                mine = fresh.get(tkr)
                if not mine:
                    stat["ticker_absent_from_fetch"] += 1
                    continue
                theirs = dict(zip(cs["d"], cs["p"], strict=False))
                anchors = {o: p for o, p in theirs.items() if o != slim_newest}
                floor_from = min(mine)
                # `<= newest` (was `< newest` until 2026-09-29): the NEWEST session is floored too. At 00:04 IST
                # on 09-29 Yahoo served 09-28 with close=null for ~3,500 tickers; 09-28 was the fetch's newest
                # session, so the strict bound let a published full session collapse 5,032 -> 1,490 (runbook §1b-iv).
                gaps = [o for o in theirs if o not in mine and floor_from <= o <= newest]
                for o in gaps:
                    if o not in off2ts:
                        stat["skip_no_session_ts"] += 1
                        continue
                    if not basis_ok(mine, anchors, o):
                        continue
                    added.setdefault(tkr, {})[o] = round(theirs[o] / 100, 2)
                    stat["floor_restored"] += 1

    # ---- pass 2: the recorded heal ledger ------------------------------------------------
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as fh:
            fills = json.load(fh).get("fills", {})
        for tkr, rows in fills.items():
            if tkr in replaced:
                stat["ledger_skip_replaced_by_store"] += 1
                continue
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
        if stat[key] and key not in ("ledger_filled",):
            print(f"       {key}: {stat[key]}", flush=True)
    if per_session:
        print("       per session (bars re-added):", flush=True)
        for o in sorted(per_session):
            print(f"         {off2date(o)}  +{per_session[o]}", flush=True)

    if dropped:
        print(
            "       phantom sessions dropped: "
            + ", ".join(f"{d} (-{n})" for d, n in sorted(dropped.items())),
            flush=True,
        )
    if total or dropped:
        with open(FRESH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        print(f"heal: rewrote {FRESH}", flush=True)
    else:
        print("heal: nothing to restore — file untouched", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
