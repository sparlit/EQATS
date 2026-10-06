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
# -*- coding: utf-8 -*-
"""Fill the dashboard price payload (scripts/stock_data.json, built by fetch_all.py from Yahoo)
for every `.NS` ticker Yahoo returned NOTHING for, from the NSE-bhavcopy store
(docs/sf_stock_data.bin release asset). DATA_RUNBOOK §145.

WHY: the dashboard universe now carries NSE's SME platform (SM/ST/SZ) and every main-board
series (EQ/BE/BZ). Yahoo has no chart for most SME tickers (SUNLITE.NS -> "Not Found",
measured 2026-09-22: 21 of 31 sampled) and types the rest MUTUALFUND, which fetch_all rejects
by design. Without this pass those rows would ship metadata-only ("—" prices) forever.

RULE: fill ONLY where Yahoo's series is empty — never mix two sources inside one ticker (the two
adjust splits on different bases). Provenance rides on meta[ticker]["src"] = "nse-bhavcopy".

NIFTY 500 REPLACE (DATA_RUNBOOK §214a F1, user 2026-09-28 "F1 option 1"): for every `.NS` ticker that was
EVER a Nifty 500 member (scripts/indices_history.json), the Yahoo history is REPLACED by the store's series.
The second-reader audit (§214 px_nse_yahoo), re-read against NSE bhavcopies, NSE/BSE corporate-action
records and Screener, found Yahoo wrong in 2,658 stretches of 263 members: splits adjusted only back to
1 January of the ex year (TRENT, MOTILALOFS, CGCL, GPIL, CONCOR), splits applied twice (LMW, VOLTAS, ABB),
whole sessions repeating the prior close (18-Mar-2025 for 492 members), time-shifted weekly bars, frozen
series. Yahoo still serves every one of them live, so only a replacement sticks.
  * History = the store: NSE official closes under our split/bonus AND demerger/rights ledgers, i.e. the
    series the stock page and backtests already read. The store is published ~20:45 IST
    (refresh-backtest-data.yml) and this job runs 15:30-17:00 IST, so the store ends at the previous
    session: Yahoo's bars dated AFTER the store's last session (normally today's one bar) are kept as the
    tail (meta tailYahoo = how many).
  * SEAM GATE: the tail is only safe on the same basis. Of the last 5 sessions both carry up to the store's
    end, >= 4 must agree within 1 % (one stale Yahoo print passes). A split whose ex-date falls in that
    window and that only one side has applied fails it, and the ticker KEEPS its Yahoo series this run.
  * A symbol whose store series ends > 10 days before the store's end (suspended) keeps Yahoo.
  * scripts/dash_px_keep_yahoo.json: members whose STORE carries a verified >= 10 % error that Yahoo does
    not (old splits missing from our ledgers, §214a L1). They keep Yahoo until the store is healed.
  * Provenance: meta src "nse-bhavcopy" + srcFrom "yahoo-replaced". heal_price_series.py skips these rows
    (its floor re-adds bars from the last published build and would mix the two sources back in).
The store is STREAMED one symbol at a time (xcheck.common.iter_section): json.loads of the whole 582 MB
bin builds ~10 GB of Python objects.

SHAPE: exactly what fetch_all emits — [[unix_ts, close], ...], WEEKLY closes before 2020-01-01
(one bar per ISO week, stamped on that week's Monday 09:15 IST, the week's LAST close — Yahoo's
1wk convention) and DAILY closes from 2020-01-01 (stamped 09:15 IST = 03:45 UTC, Yahoo's
convention for .NS daily bars, so build_compressed's day offsets line up with Yahoo-sourced rows).

Non-fatal by design in the workflow: if the release asset cannot be fetched the Yahoo-only
payload still ships, and the step prints a ::warning:: so the gap is visible, not silent.

Env: SF_BIN=<path> reads a local bin instead of downloading the release asset (tests).
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import contextlib
import datetime
import gzip
import json
import os
import time
from pathlib import Path

import bse_headers as BH  # §181 BSE headers
from xcheck import (
    common as XC,
)  # streaming reader of the price bin (iter_section / late_value / sf_path)

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = ROOT / "scripts" / "stock_data.json"
DAILY_FROM = 20200101
END_TS_NOW = int(time.time())
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
INDICES_HISTORY = ROOT / "scripts" / "indices_history.json"
KEEP_YAHOO = ROOT / "scripts" / "dash_px_keep_yahoo.json"
SEAM_N, SEAM_OK, SEAM_TOL = 5, 4, 0.01  # of the last 5 shared sessions, >= 4 within 1 %
STALE_DAYS = 10  # store series ending this long before the store's end = suspended


def bin_path():
    """Local path of the store: SF_BIN when set, else the release asset downloaded (and checked to be a
    complete gzip) by xcheck.common.sf_path — 3 tries, then SystemExit (the workflow step is non-fatal)."""
    p = os.environ.get("SF_BIN")
    print("sf-fill: base = %s" % (("local file " + p) if p else "release asset"), flush=True)
    p = XC.sf_path()
    print(f"sf-fill: store file {p} ({os.path.getsize(p) / 1048576:.1f} MB gz)", flush=True)
    return p


def ymd_int(v):
    """20260925 from 20260925 / "2026-09-25" / "20260925"."""
    return int(str(v).replace("-", ""))


def ymd_of_ts(ts):
    d = datetime.datetime.fromtimestamp(ts, IST).date()
    return d.year * 10000 + d.month * 100 + d.day


def n500_replace_set(meta, series):
    """{ticker: symbol} for every `.NS` ticker with a Yahoo series whose symbol was EVER in the Nifty 500
    (every snapshot in scripts/indices_history.json), minus the keep-Yahoo ledger. Also returns the ledger."""
    try:
        ih = json.loads(INDICES_HISTORY.read_text(encoding="utf-8"))["Nifty 500"]
    except Exception as e:
        print(
            f"sf-fill: WARNING {INDICES_HISTORY} unreadable ({e}) — Nifty 500 replacement skipped",
            flush=True,
        )
        return {}, {}
    ever = set()
    for snap in ih:
        ever.update(snap.get("symbols") or [])
    try:
        keep = json.loads(KEEP_YAHOO.read_text(encoding="utf-8")).get("keep") or {}
    except FileNotFoundError:
        keep = {}
    out = {}
    for t, m in meta.items():
        if not t.endswith(".NS") or not series.get(t):
            continue
        sym = ((m or {}).get("symbol") or t[:-3]).upper()
        if sym in ever and sym not in keep:
            out[t] = sym
    return out, keep


def replace_one(t, e, series, cal, end):
    """Replace ticker t's Yahoo series with the store entry e (+ Yahoo's bars after `end`).
    Returns (None, n_tail, dropped) on success, (reason, detail, 0) when the ticker keeps Yahoo."""
    ybars = series[t]
    if not e.get("d"):
        return "no store series", "", 0
    last = e["d"][-1]
    if (
        datetime.date(end // 10000, end // 100 % 100, end % 100)
        - datetime.date(last // 10000, last // 100 % 100, last % 100)
    ).days > STALE_DAYS:
        return "store series ends %d" % last, "", 0
    yd = {ymd_of_ts(ts): c for ts, c in ybars if ts >= ts_of(DAILY_FROM)}
    shared = [
        (d, c)
        for d, c in zip(e["d"], e["c"], strict=False)
        if DAILY_FROM <= d <= end and c and d in yd and yd[d]
    ]
    seam = shared[-SEAM_N:]
    good = sum(1 for d, c in seam if abs(yd[d] / c - 1) <= SEAM_TOL)
    if len(seam) < 3 or good < min(SEAM_OK, len(seam)):
        return "seam", " ".join("%d:%.2f/%.2f" % (d, yd[d], c) for d, c in seam), 0
    bars, dropped = series_from(e, cal)
    tail = [b for b in ybars if ymd_of_ts(b[0]) > end]
    series[t] = bars + tail
    return None, len(tail), dropped


def ts_of(ymd, weekday_monday=False):
    d = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
    if weekday_monday:
        d = d - datetime.timedelta(days=d.weekday())
    return int(datetime.datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST).timestamp())


def yahoo_calendar(meta, series):
    """The set of daily-era session dates (ymd ints) that THIS build's Yahoo-sourced series carry.
    The dashboard store is a Yahoo-calendar store: Yahoo publishes no bar for NSE's weekend special
    sessions (the Budget Sunday 2026-02-01 — 2,956 symbols in the bhavcopy store, 0 on Yahoo), so a
    filled series that kept such a bar would be among the only tickers with that session, and
    guard_sessions.py rightly reads a session held by 405 of 4,800 tickers as HALF-LOADED (exactly how
    the first SME run failed, 2026-09-22 11:48Z). Filled series therefore follow the same calendar as
    the Yahoo rows they sit beside; a session Yahoo does not have is not emitted."""
    days = set()
    floor = ts_of(DAILY_FROM)
    for t, ser in series.items():
        if (meta.get(t) or {}).get("src") == "nse-bhavcopy":
            continue  # only Yahoo-sourced rows vote
        for ts, _c in ser:
            if ts >= floor:
                d = datetime.datetime.fromtimestamp(ts, IST).date()
                days.add(d.year * 10000 + d.month * 100 + d.day)
    return days


def series_from(e, cal=None):
    """bin entry {d:[ymd], c:[adj close]} -> [[ts, close]] in fetch_all's weekly-then-daily shape.
    `cal` = the Yahoo session calendar (yahoo_calendar); daily bars on dates outside it are dropped.
    Returns (bars, dropped)."""
    weekly, daily, dropped = (
        {},
        [],
        0,
    )  # weekly: (iso year, iso week) -> bar; bars arrive in date order,
    for ymd, c in zip(
        e["d"], e["c"], strict=False
    ):  # so the last assignment per week is that week's LAST close
        if c is None or c <= 0:
            continue
        if ymd >= DAILY_FROM:
            if cal is not None and ymd not in cal:
                dropped += 1
                continue
            daily.append([ts_of(ymd), round(float(c), 2)])
        else:
            dt = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
            weekly[dt.isocalendar()[:2]] = [ts_of(ymd, weekday_monday=True), round(float(c), 2)]
    out = list(weekly.values()) + daily
    out.sort(key=lambda b: b[0])
    return out, dropped


BSE_PX = ROOT / "docs" / "bse_prices.bin"  # BSE daily bhavcopy closes (fetch_bse_bhav.py), RAW
BSE_UNIV = ROOT / "docs" / "bse_universe.json"
CA_FRACS = [
    1 / 2,
    1 / 3,
    2 / 3,
    1 / 4,
    3 / 4,
    1 / 5,
    2 / 5,
    3 / 5,
    1 / 6,
    5 / 6,
    1 / 8,
    1 / 10,
    1 / 20,
    1 / 50,
    2.0,
    3.0,
    4.0,
    5.0,
    10.0,
]


def ca_factor(r):
    """build_sf_data's corporate-action ladder: a close-to-close ratio outside [0.75, 1.30] within 8% of a
    canonical split/bonus fraction is a corporate action, anything else a real move. On BSE's X/XT/M
    groups the daily band is 5-20%, so a ratio that far out between two TRADES is not a market move."""
    if 0.75 <= r <= 1.30:
        return 1.0
    for f in CA_FRACS:
        if abs(r / f - 1) <= 0.08:
            return f
    return 1.0


CA_LEDGER = (
    ROOT / "scripts" / "bse_ca_checks.json"
)  # {"code|ymd": verdict} — BSE's own record per candidate step


def bse_official(code, ymd, cache):
    """What BSE's corporate-action record says within 7 days of a candidate step: "split_bonus",
    "other" (spin-off / demerger / scheme / anything else) or "none". A step that looks like a split
    by its ratio is NOT divided out unless BSE records a split or bonus: AG Ventures fell 809.85 ->
    209.50 on 2024-07-01 (ratio 0.259, "1:4" by shape) and BSE's record for that day is a SPIN OFF —
    real value left the stock, and dividing it out would have invented the whole earlier history."""
    key = "%s|%d" % (code, ymd)
    if key in cache:
        return cache[key]
    d = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
    f, t = (
        (d - datetime.timedelta(days=7)).strftime("%Y%m%d"),
        (d + datetime.timedelta(days=7)).strftime("%Y%m%d"),
    )
    url = (
        f"https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w?Fdate={f}&Purposecode=&ScripCode={code}"
        f"&segment=0&strSearch=S&TDate={t}"
    )
    try:
        import subprocess

        out = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-A", BH.UA, *BH.CURL_ARGS, url],
            capture_output=True,
            timeout=45,
        ).stdout
        rows = json.loads(out or b"[]")
    except Exception:
        return "unknown"  # not cached: retried next run
    purposes = (
        " | ".join(str(r.get("Purpose") or "") for r in rows) if isinstance(rows, list) else ""
    )
    low = purposes.lower()
    v = (
        "split_bonus"
        if ("split" in low or "bonus" in low)
        else ("other" if purposes.strip() else "none")
    )
    cache[key] = v
    print(
        "  bse-fill: %s step on %d -> BSE record: %s (%s)"
        % (code, ymd, v, purposes.strip() or "nothing"),
        flush=True,
    )
    return v


def adjusted(e, code=None, cache=None):
    """RAW closes -> split/bonus-adjusted closes, re-anchored so the last value is the last RAW close
    (the same convention as the NSE store). A ratio-shaped step is divided out ONLY when BSE records a
    split or bonus there (bse_official); spin-offs, schemes and unexplained steps stay as real moves.
    Returns ({"d","c"}, n_actions)."""
    d, c = e["d"], e["c"]
    adj, out, n = None, [], 0
    for i, x in enumerate(c):
        if adj is None:
            adj = x
        else:
            r = (x / c[i - 1]) if c[i - 1] else 1.0
            f = ca_factor(r)
            if (
                f != 1.0
                and code is not None
                and bse_official(code, d[i], cache if cache is not None else {}) != "split_bonus"
            ):
                f = 1.0
            if f != 1.0:
                n += 1
            adj = adj * (r / f)
        out.append(adj)
    k = (c[-1] / out[-1]) if out and out[-1] else 1.0
    return {"d": d, "c": [round(v * k, 2) for v in out]}, n


def fill_bse(meta, series, cal):
    """`.BO` rows Yahoo has no chart for -> series from BSE's own bhavcopy store (docs/bse_prices.bin,
    2023-12 -> date). Measured 2026-09-23: 28 such rows had BSE trades in the store (Hindustan Motors,
    AG Ventures, Team24 … 675+ sessions each) while the dashboard showed them price-less (§145)."""
    todo = [t for t in meta if t.endswith(".BO") and not series.get(t)]
    if not todo:
        return
    try:
        px = json.loads(gzip.decompress(BSE_PX.read_bytes()))["px"]
    except Exception as e:
        print(f"bse-fill: {BSE_PX} unreadable ({e}) — skipped")
        return
    sid2code = {}
    try:
        for r in json.loads(BSE_UNIV.read_text(encoding="utf-8"))["rows"]:
            sid2code[str(r[1]).upper()] = str(r[0])
    except Exception:
        pass
    try:
        for b in json.load(open("/tmp/bse.json", encoding="utf-8")):
            sid, code = (b.get("scrip_id") or "").strip().upper(), (b.get("SCRIP_CD") or "").strip()
            if sid and code:
                sid2code.setdefault(sid, code)
    except Exception:
        pass
    try:
        cache = json.loads(CA_LEDGER.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    filled = actions = dropped_total = 0
    short = []
    for t in todo:
        base = t[:-3]
        code = base if base.isdigit() else sid2code.get(base.upper())
        e = px.get(code) if code else None
        if not e or not e.get("d"):
            short.append(t)
            continue
        a, n = adjusted(e, code, cache)
        ser, dropped = series_from(a, cal)
        if not long_enough(ser, END_TS_NOW):
            short.append(t)
            continue
        series[t] = ser
        meta[t]["src"] = "bse-bhavcopy"
        filled += 1
        actions += n
        dropped_total += dropped
    with contextlib.suppress(Exception):
        CA_LEDGER.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    print(
        "bse-fill: %d of %d price-less .BO rows filled from BSE's bhavcopy store (%d split/bonus "
        "steps divided out, each confirmed by BSE's record; %d off-calendar bars dropped); %d have < 2 BSE trades since 2023-12"
        % (filled, len(todo), actions, dropped_total, len(short)),
        flush=True,
    )


def long_enough(ser, end_ts):
    """>= 2 bars, or a single bar from the last 7 days (a listing-day stock; the page shows "Day 1")."""
    return len(ser) >= 2 or (len(ser) == 1 and end_ts - ser[0][0] <= 7 * 86400)


def main():
    payload = json.loads(PAYLOAD.read_text())
    meta, series = payload["meta"], payload["series"]
    todo = [t for t in meta if t.endswith(".NS") and not series.get(t)]
    print(
        "sf-fill: %d .NS tickers with no Yahoo series (of %d)" % (len(todo), len(meta)), flush=True
    )
    cal = yahoo_calendar(meta, series)
    if len(cal) < 200:
        print(
            "sf-fill: WARNING only %d Yahoo daily sessions in this payload — calendar alignment skipped"
            % len(cal),
            flush=True,
        )
        cal = None
    fill_bse(meta, series, cal)  # BSE rows first: needs no download
    # The Nifty 500 replace set is taken before any .NS fill: it is defined by the Yahoo series it replaces.
    repl, keep = n500_replace_set(meta, series)
    if cal is not None:
        cal = yahoo_calendar(meta, series)
        if len(cal) < 200:
            # a Yahoo build with fewer than 200 daily sessions is not a calendar anyone should follow —
            # fill uncut and say so, rather than emit 200-bar stubs for every SME name
            print(
                "sf-fill: WARNING only %d Yahoo daily sessions in this payload — calendar alignment skipped"
                % len(cal),
                flush=True,
            )
            cal = None
        else:
            print(
                "sf-fill: Yahoo calendar = %d daily sessions (%d..%d); filled bars outside it are dropped"
                % (len(cal), min(cal), max(cal)),
                flush=True,
            )
    if repl and cal is None:
        # without the calendar a replaced series would carry sessions no Yahoo row has (Budget Sunday …)
        # and guard_sessions reads those as half-loaded days: ship Yahoo for this run instead
        print(
            "sf-fill: WARNING no usable Yahoo calendar — Nifty 500 replacement SKIPPED this run (%d Yahoo series ship)"
            % len(repl),
            flush=True,
        )
        repl = {}
    if not todo and not repl:
        payload["series"] = series
        PAYLOAD.write_text(json.dumps(payload, separators=(",", ":")))
        print("sf-fill: no .NS gaps and nothing to replace")
        return
    path = bin_path()
    end = ymd_int(XC.late_value(path, "end"))
    want = {}  # symbol -> [(job, ticker)]
    for t in todo:
        want.setdefault((meta[t].get("symbol") or t[:-3]).upper(), []).append(("fill", t))
    for t, sym in repl.items():
        want.setdefault(sym, []).append(("repl", t))
    seen = set()
    filled, absent, short, dropped_total, dropped_days = 0, [], [], 0, {}
    replaced, kept, tails, rep_dropped = 0, [], {}, 0
    for sym, raw in XC.iter_section(path, "data"):
        jobs = want.get(sym)
        if not jobs:
            continue
        seen.add(sym)
        e = json.loads(raw)
        for job, t in jobs:
            if job == "repl":
                why, info, dropped = replace_one(t, e, series, cal, end)
                if why:
                    kept.append((sym, why, info))
                    continue
                meta[t]["src"] = "nse-bhavcopy"  # provenance: the store's series …
                meta[t]["srcFrom"] = (
                    "yahoo-replaced"  # … replacing a Yahoo one (heal_price_series skips it)
                )
                meta[t]["tailYahoo"] = info  # Yahoo bars kept after the store's last session
                replaced += 1
                rep_dropped += dropped
                tails[info] = tails.get(info, 0) + 1
                continue
            if not e.get("d"):
                absent.append(sym)
                continue
            ser, dropped = series_from(e, cal)
            if not long_enough(ser, END_TS_NOW):
                short.append(sym)
                continue
            series[t] = ser
            meta[t]["src"] = "nse-bhavcopy"  # provenance: not a Yahoo series
            filled += 1
            dropped_total += dropped
            if cal is not None and dropped:
                for ymd in e["d"]:
                    if ymd >= DAILY_FROM and ymd not in cal:
                        dropped_days[ymd] = dropped_days.get(ymd, 0) + 1
    for sym, jobs in want.items():
        if sym in seen:
            continue
        for job, t in jobs:
            if job == "repl":
                kept.append((sym, "not in the store", ""))
            else:
                absent.append(sym)
    payload["series"] = series
    PAYLOAD.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        "sf-fill: filled %d series from the bhavcopy store (bin end %s); %d symbols not in the store, %d too short; "
        "%d bars on %d non-Yahoo sessions dropped%s"
        % (
            filled,
            end,
            len(absent),
            len(short),
            dropped_total,
            len(dropped_days),
            (" (" + ", ".join("%d x%d" % kv for kv in sorted(dropped_days.items())[-8:]) + ")")
            if dropped_days
            else "",
        ),
        flush=True,
    )
    if absent:
        print("  not in store (first 40): {}".format(", ".join(sorted(absent)[:40])))
    if short:
        print("  too short: {}".format(", ".join(sorted(short)[:40])))
    print(
        "sf-fill: Nifty 500 REPLACE: %d of %d ever-member Yahoo series replaced by the store (end %d); Yahoo tail bars "
        "after it: %s; %d store bars on non-Yahoo sessions dropped; %d kept Yahoo by ledger (%s)"
        % (
            replaced,
            len(repl),
            end,
            ", ".join("%d bar(s) x%d" % kv for kv in sorted(tails.items())) or "none",
            rep_dropped,
            len(keep),
            ", ".join(sorted(keep)) or "-",
        ),
        flush=True,
    )
    if kept:
        print(
            "sf-fill: WARNING %d member(s) KEPT their Yahoo series this run:" % len(kept),
            flush=True,
        )
        for sym, why, info in sorted(kept)[:40]:
            print(f"  {sym}: {why} {info}", flush=True)
    print(
        "sf-fill: payload now %d tickers with prices of %d"
        % (sum(1 for t in meta if series.get(t)), len(meta)),
        flush=True,
    )


if __name__ == "__main__":
    main()
