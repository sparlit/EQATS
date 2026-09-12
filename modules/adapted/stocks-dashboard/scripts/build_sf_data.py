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
"""
FULL survivorship-free price+turnover database from NSE daily bhavcopies.

  * Fetches DAILY (one bhavcopy = all stocks for that day) from START..today, so
    splits/bonuses adjust correctly via NSE's corporate-action-adjusted PREV_CLOSE
    (we chain daily returns close/prev_close into a clean adjusted index).
  * STORES weekly samples before DAILY_FROM (deep history, small) and daily after.
  * Includes every stock that ever traded — delisted ones too (kills survivorship bias).

Resumable: caches each day's parsed rows under scripts/_bhav_cache/ so re-runs skip
already-downloaded days. Output: docs/sf_stock_data.bin (gzip JSON the backtest fetches).

Run:  python -X utf8 build_sf_data.py [START=1996-01-01] [DAILY_FROM=2018-01-01]
"""
import contextlib
import csv
import datetime
import gzip
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "_bhav_cache")
os.makedirs(CACHE, exist_ok=True)
OUT = os.path.join(ROOT, "docs", "sf_stock_data.bin")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

START = datetime.date(1996, 1, 1)
DAILY_FROM = datetime.date(2018, 1, 1)
if len(sys.argv) > 1:
    START = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
if len(sys.argv) > 2:
    DAILY_FROM = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
END = datetime.date.today()

# ---- ALIVENESS ------------------------------------------------------------------------------
# `alive` answers ONE question for every consumer that reads it (stock.html's "delisted" badge AND
# its `.NS` live-quote fetch, build_quarterly_results, build_results_season, build_stock_slices,
# backfill_gaps, the two backtest engines' nDead): **is this NSE series still being appended?**
# It used to be exactly `sym in cur`, i.e. membership of docs/dash_slim.bin — the WRONG oracle,
# two ways (DATA_RUNBOOK §94):
#   · dash_slim is an NSE **+ BSE** universe keyed `SYM.NS` / `SYM.BO` (measured 2026-08-12:
#     2,131 .NS + 2,739 .BO) and the lookup below STRIPS the suffix. So a company that left the
#     NSE cash segment but still trades on BSE marked its DEAD NSE tape alive. Measured on the
#     live bin (end 2026-08-11): 87 symbols carried alive=True with a last bar >60d old, ALL 87
#     matched through a `.BO` key and 0 through `.NS`; 0 of the 87 appear on the last 10 sessions
#     of the raw bhavcopy or in today's EQUITY_L. PUNJCOMMU (BSE 500346) is the worked example —
#     its NSE tape stopped 2003-03-31 and the flag still said alive 23 years later.
#   · the flag is only recomputed by a FULL rebuild (or patch_sf_alive.py), so it never DECAYS:
#     a stock that stops trading keeps alive=True until someone re-runs a multi-hour rebuild.
# Fix: a freshness NECESSARY CONDITION, ANDed onto whatever the membership lookup says. It only
# ever takes aliveness AWAY, so it cannot resurrect a symbol or invent one (see veto_stale_alive).
ALIVE_RECENCY_DAYS = 60  # same window, and the same measured justification, as
# build_results_season.RECENCY_DAYS — that docstring shows the
# age-of-last-bar histogram is bimodal with nothing between ~8d and
# ~170d, so every cutoff in that range gives identical membership.


def alive_cutoff(end, days=ALIVE_RECENCY_DAYS):
    """YYYYMMDD int that a series' LAST bar must reach to count as alive, or None if `end` is
    unusable. `end` is the DATASET's own end, NEVER today's date: a frozen snapshot has to be
    judged against itself or it declares its whole universe dead (§11 recency guard, same trap)."""
    try:
        e = datetime.date(*(int(x) for x in str(end).split("-")[:3]))
    except Exception:
        return None
    c = e - datetime.timedelta(days=days)
    return c.year * 10000 + c.month * 100 + c.day


def veto_stale_alive(data, meta, end, days=ALIVE_RECENCY_DAYS):
    """Clear `alive` on every series whose last bar is older than `days` before `end`; return how
    many flags changed. ONE DIRECTION ONLY — it turns a stale True off and never turns anything on,
    so it cannot mis-kill a symbol the caller has no listing oracle for (dash_slim's NSE side is a
    SUBSET of the tape: 384 currently-trading symbols sit at alive=False today, §94c) and it cannot
    resurrect one. Idempotent by construction: a converged file reports 0, so it is safe to run
    every night (the daily updater does)."""
    cutoff = alive_cutoff(end, days)
    if cutoff is None:
        print(f"  ⚠ alive-recency: bin has no usable `end` ({end!r}) — flags left untouched", flush=True)
        return 0
    n = 0
    for sym, m in meta.items():
        if not isinstance(m, dict) or not m.get("alive"):
            continue
        d = (data.get(sym) or {}).get("d")
        if not d or d[-1] < cutoff:
            m["alive"] = False
            n += 1
    return n


def jar():
    j = http.cookiejar.CookieJar()
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
        op.open(urllib.request.Request("https://www.nseindia.com/", headers={"User-Agent": UA}), timeout=20).read()
    except Exception:
        pass
    return j


def get(url, j, timeout=30):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
    with op.open(req, timeout=timeout) as r:
        return r.read()


def parse_rows(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    hdr = [h.strip().upper() for h in rows[0]]

    def idx(*ns):
        for n in ns:
            if n in hdr:
                return hdr.index(n)
        return -1

    iS, iSer = idx("SYMBOL"), idx("SERIES")
    iC, iP, iT = idx("CLOSE_PRICE", "CLOSE"), idx("PREV_CLOSE", "PREVCLOSE"), idx("TURNOVER_LACS", "TOTTRDVAL")
    iH, iL, iO = idx("HIGH_PRICE", "HIGH"), idx("LOW_PRICE", "LOW"), idx("OPEN_PRICE", "OPEN")
    iV, iN = idx("TTL_TRD_QNTY", "TOTTRDQTY"), idx("NO_OF_TRADES", "TOTALTRADES")
    iD, iW, iI = idx("DELIV_PER"), idx("AVG_PRICE"), idx("ISIN")
    if iS < 0 or iC < 0:
        return []

    def num(r, i, dflt=0.0):
        if i < 0 or i >= len(r):
            return dflt
        s = r[i].strip()
        if not s or s == "-":
            return dflt
        try:
            return float(s)
        except ValueError:
            return dflt

    out = []
    for r in rows[1:]:
        if len(r) <= max(iS, iC):
            continue
        ser = r[iSer].strip() if iSer >= 0 else "EQ"
        # THE EQUITY CASH SEGMENT IS THREE SERIES, NOT TWO. All of EQ/BE/BZ are ordinary listed
        # companies trading every session; everything else in this file is a different instrument
        # (SM/ST = SME platform, GS/GB/TB = govt securities & bonds, IV = InvIT, N*/Y*/Z* = debt,
        # RR/E1/MF/... = rights entitlements, ETFs and friends) and stays out.
        #   EQ = normal rolling settlement.
        #   BE = trade-for-trade (compulsory delivery, no intraday netting).
        #   BZ = trade-for-trade PLUS surveillance — companies that have not complied with a
        #        listing/regulatory requirement. A BZ stock is still LISTED and still trades daily.
        # BZ was excluded until 2026-08-10 and that silently TRUNCATED a live series: a stock's
        # bars simply stopped on the day it was penalised into BZ and resumed only if it was
        # promoted back. Measured that day against NSE's EQUITY_L.csv + the fresh bin (end
        # 2026-08-07): EQ 2,086 symbols / 0 stale, BE 285 / 0 stale, BZ 39 / 38 STALE — HDIL frozen
        # at 2020-03-02 and RAJESHEXPO at 2025-12-24 while both traded that very week (verified in
        # the bhavcopy and independently on Yahoo). The bars are all there in the file: a BZ row
        # carries the same OPEN/HIGH/LOW/CLOSE/PREV_CLOSE/TTL_TRD_QNTY/TURNOVER_LACS/NO_OF_TRADES
        # as an EQ row. Mid-series holes were the same defect: UNITECH went BZ 2020-03 -> 2025-10
        # and traded Rs16 cr on a sampled day inside the hole. See DATA_RUNBOOK §80.
        if ser not in ("EQ", "BE", "BZ"):
            continue
        c = num(r, iC)
        if c <= 0:
            continue
        dlv = num(r, iD)
        # BE and BZ are both trade-for-trade: every trade settles with delivery, so NSE prints
        # DELIV_QTY *and* DELIV_PER as '-' for both (measured 2026-08-07: every one of the 291 BE
        # and 27 BZ rows dashed, every one of the 2,416 EQ rows numeric). Store the true 100
        # instead of the 0 sentinel (0 must mean "unavailable" only).
        if ser in ("BE", "BZ") and iD >= 0 and dlv == 0:
            dlv = 100.0
        # FULL row cached so future factor additions never need a refetch:
        # [sym, close, prevclose, turnover, high, low, open, volume, deliv%, vwap, trades, isin, series]
        # `series` is last and is also the CACHE VERSION MARKER — fetch_day/needs_fetch require >=13
        # columns, so any day cached under the old EQ/BE-only filter is refetched instead of being
        # replayed BZ-less. Append new columns at the END only; readers index by position.
        out.append(
            [
                r[iS].strip(),
                c,
                num(r, iP),
                num(r, iT),
                num(r, iH, c),
                num(r, iL, c),
                num(r, iO, c),
                num(r, iV),
                dlv,
                num(r, iW),
                num(r, iN),
                (r[iI].strip() if 0 <= iI < len(r) else ""),
                ser,
            ]
        )
    return out


def apply_dv_fill(data):
    """Fill-only delivery-%% ledgers (tracked): dv_fill.json (2020+ heal: sec_bhavdata re-reads,
    BE/T2T '-' days as 100) + dv_fill_hist.json.gz (2002-2019 backfill from the MTO security-wise
    delivery files — the pre-2020 bhavcopies carry no DELIV_PER at all). Writes only where dv is
    0 and the date row exists, so it is idempotent and can never clobber a real value. Ledger
    keys are MERGED (current) symbols — on a from-scratch rebuild (era symbols, pre-merge)
    unmatched keys are skipped here and re-applied by update_sf_data on the merged release asset."""
    n = 0
    for fname in ("dv_fill.json", "dv_fill_hist.json.gz"):
        p = os.path.join(HERE, fname)
        if not os.path.exists(p):
            continue
        try:
            fh = gzip.open(p, "rt", encoding="utf-8") if fname.endswith(".gz") else open(p)
            fills = json.load(fh).get("fills", {})
        except Exception as e:
            print(f"{fname} unreadable ({e}) — skipped", flush=True)
            continue
        k = 0
        for sym, days in fills.items():
            s = data.get(sym)
            if not s:
                continue
            pos = {d: i for i, d in enumerate(s["d"])}
            for ds, v in days.items():
                i = pos.get(int(ds))
                if i is not None and not s["dv"][i]:
                    s["dv"][i] = v[0] if isinstance(v, list) else v
                    k += 1
        if k:
            print("%s applied: %d delivery%% cells" % (fname, k), flush=True)
        n += k
    return n


def apply_dv_overwrite(data):
    """One-shot OVERWRITE ledger (scripts/dv_overwrite.json) for the §88b wrong-company delivery
    cells — dv>0 values the fill-only ledgers can never reach. Each cell carries [old, new, vol];
    a bar is rewritten only while it still matches BOTH anchors (dv == old ±0.011 AND v == vol,
    the volume of the MTO row that adjudicated the cell), so the pass is idempotent (§87e-bis:
    second run rewrites 0) and cannot touch a bar it did not adjudicate. Cells already at the
    correct value count as done; anything else is LEFT ALONE and printed (silence lies, §38b)."""
    p = os.path.join(HERE, "dv_overwrite.json")
    if not os.path.exists(p):
        return 0
    try:
        cells = json.load(open(p)).get("cells", {})
    except Exception as e:
        print(f"dv_overwrite.json unreadable ({e}) — skipped", flush=True)
        return 0
    n = done = left = 0
    for sym, days in cells.items():
        s = data.get(sym)
        if not s:
            left += len(days)
            continue
        pos = {d: i for i, d in enumerate(s["d"])}
        for ds, (oldv, newv, vol) in days.items():
            i = pos.get(int(ds))
            cur = s["dv"][i] if i is not None else None
            if cur is None:
                left += 1
            elif abs(cur - newv) <= 0.011:
                done += 1
            elif abs(cur - oldv) <= 0.011 and s["v"][i] == vol:
                s["dv"][i] = newv
                n += 1
            else:
                left += 1
    if n or left:
        print(
            "dv_overwrite.json: %d cells overwritten, %d already correct, %d left alone (no matching bar)"
            % (n, done, left),
            flush=True,
        )
    return n


def fetch_day(d, j):
    cf = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
    if os.path.exists(cf):
        try:
            rows = json.load(open(cf))
            # older cache rows lack the full column set (v3 = 12 cols, v4 = 13 with `series`, which
            # is also the marker for "parsed under the EQ/BE/BZ filter") — refetch; holiday [] reusable
            if not rows or len(rows[0]) >= 13:
                return rows
        except Exception:
            pass
    ddmmyyyy = d.strftime("%d%m%Y")
    new = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
    old = "https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip" % (
        d.year,
        MON[d.month - 1],
        d.day,
        MON[d.month - 1],
        d.year,
    )
    for url in [new, old] if d.year >= 2020 else [old, new]:
        try:
            blob = get(url, j)
            text = (
                zipfile.ZipFile(io.BytesIO(blob))
                .read(zipfile.ZipFile(io.BytesIO(blob)).namelist()[0])
                .decode("utf-8", "replace")
                if url.endswith(".zip")
                else blob.decode("utf-8", "replace")
            )
            if "SYMBOL" in text[:200].upper():
                rows = parse_rows(text)
                json.dump(rows, open(cf, "w"))
                return rows
        except Exception:
            continue
    # cache the miss (holiday) so we don't refetch — but NOT for the last few days:
    # a same-evening build can run before NSE publishes today's file (~7 pm IST),
    # and a cached empty marker would wrongly freeze that day as a holiday forever.
    if d < datetime.date.today() - datetime.timedelta(days=4):
        json.dump([], open(cf, "w"))
    return []


def needs_fetch(d):
    cf = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
    if not os.path.exists(cf):
        return True
    try:
        rows = json.load(open(cf))
        return bool(rows) and len(rows[0]) < 13  # pre-v4 cache (no `series` col / BZ-less) -> refetch
    except Exception:
        return True


def prefetch_parallel(dates, workers=6):
    """Fill the cache in parallel (nsearchives is a static CDN; modest concurrency is fine)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    local = threading.local()

    def work(d):
        if not hasattr(local, "jar"):
            local.jar = jar()
        with contextlib.suppress(Exception):
            fetch_day(d, local.jar)
        time.sleep(0.05)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(work, dates):
            done += 1
            if done % 500 == 0:
                print("  prefetch %d/%d" % (done, len(dates)), flush=True)


def main():
    all_days = []
    d = START
    while d <= END:
        # ALL calendar days — weekend special sessions (budget Saturdays, weekend muhurat,
        # DR-drill Saturdays) are real trading days; the old weekday()<5 filter dropped them.
        # Non-session weekends cost one cached [] miss each, and the exact-duplicate signature
        # check below already skips NSE's holiday URL misdirect (prior day's file re-served).
        all_days.append(d)
        d += datetime.timedelta(days=1)
    todo = [d for d in all_days if needs_fetch(d)]
    print("Trading-day candidates: %d | needing (re)fetch: %d" % (len(all_days), len(todo)), flush=True)
    if todo:
        prefetch_parallel(todo)

    j = jar()
    acc = {}
    isin_of = {}
    tried = got = 0
    prev_sig = None
    skipped_dupes = 0
    for d in all_days:
        tried += 1
        rows = fetch_day(d, j)  # cache hit for nearly all after prefetch
        if rows:
            # NSE's per-day URL returns the PRIOR trading day's file on holidays (wrong URL date,
            # correct date inside). Two real trading days are never byte-identical across 2600+ stocks,
            # so an exact duplicate of the previous accepted day == a holiday → skip it (else it injects
            # a fake flat day that corrupts RSI/returns).
            sig = hash(tuple((r[0], r[1]) for r in rows))
            if sig == prev_sig:
                skipped_dupes += 1
                continue
            prev_sig = sig
            got += 1
            ymd = int(d.strftime("%Y%m%d"))
            for row in rows:
                sym, c, p, t = row[0], row[1], row[2], row[3]
                h = row[4] if len(row) > 4 else c
                l = row[5] if len(row) > 5 else c
                o = row[6] if len(row) > 6 else c
                v = row[7] if len(row) > 7 else 0
                dlv = row[8] if len(row) > 8 else 0
                vw = row[9] if len(row) > 9 else 0
                if len(row) > 11 and row[11]:
                    isin_of[sym] = row[11]  # last ISIN seen (old-format files carry it)
                acc.setdefault(sym, []).append((ymd, c, p, t, h, l, o, v, dlv, vw))
        if tried % 1000 == 0:
            print("  ...%s  days=%d/%d  symbols=%d" % (d, got, tried, len(acc)), flush=True)
    print(
        "Fetched %d/%d trading days; %d symbols; skipped %d holiday-duplicate days"
        % (got, tried, len(acc), skipped_dupes),
        flush=True,
    )

    # ---- MERGE renamed tickers into ONE continuous series under the current ticker ----
    # A rename (Ami Organics AMIORG -> Acutaas ACUTAAS, GET&D -> GVT&D, ADANITRANS -> ADANIENSOL, ...)
    # starts a fresh bhavcopy series under the new ticker, which truncates every lookback window
    # (52w hi/lo, returns, RSI) and splits corporate actions for up to a year. Tickers sharing an
    # ISIN are the SAME security across the rename (a recycled ticker keeps a DIFFERENT ISIN, so this
    # never merges two real companies); symchg.csv fills pre-2020 gaps where the file carried no ISIN.
    rename_to = {}
    by_isin = {}
    for sym in acc:
        isin = isin_of.get(sym)
        if isin:
            by_isin.setdefault(isin, []).append(sym)
    for isin, syms in by_isin.items():
        if len(syms) < 2:
            continue
        canon = max(syms, key=lambda s: max(o[0] for o in acc[s]))  # latest-trading ticker = current
        for s in syms:
            if s != canon:
                rename_to[s] = canon
    recycled_split = {}  # old_sym -> (target, cutoff_ymd): ticker RE-USED by a different company later
    try:  # symchg.csv supplement (old,new)
        sc = os.path.join(HERE, "symchg.csv")
        if not os.path.exists(sc):
            sc = os.path.join(os.path.dirname(ROOT), "symchg.csv")
        for r in csv.reader(open(sc, encoding="utf-8", errors="replace")):
            if len(r) >= 3 and r[1].strip() and r[2].strip():
                o2, n2 = r[1].strip().upper(), r[2].strip().upper()
                if o2 in acc and o2 not in rename_to:
                    tgt = rename_to.get(n2, n2)
                    if tgt in acc and tgt != o2:
                        # RECYCLED-TICKER GUARD (2026-08-11, the DVL/DTIL chimera, RUNBOOK §89).
                        # The ISIN merge above is recycle-safe by construction; this dateless
                        # (old,new) bridge is NOT: NSE re-issues old symbols to unrelated companies
                        # (DTIL = Dhunseri Ventures until its 2010-07-26 rename, then Dhunseri Tea —
                        # a DIFFERENT company, different ISIN — from 2015-01-20). If the old symbol
                        # still has bars well past its own rename date it was recycled: merge only
                        # the pre-cutoff bars into the chain and keep the later company under its
                        # own key, OUT of _rename_map.json. Unparseable date -> old behavior.
                        cutoff = None
                        try:
                            cd = datetime.datetime.strptime(r[3].strip().title(), "%d-%b-%Y").date()
                            cutoff = int((cd + datetime.timedelta(days=45)).strftime("%Y%m%d"))
                        except Exception:
                            pass
                        if cutoff and max(o[0] for o in acc[o2]) > cutoff:
                            recycled_split[o2] = (tgt, cutoff)
                            print(
                                "  RECYCLED TICKER %s: bars continue past its %s rename to %s — "
                                "merging only bars <= %d; the later listing keeps the key"
                                % (o2, r[3].strip(), tgt, cutoff),
                                flush=True,
                            )
                        else:
                            rename_to[o2] = tgt
    except Exception as e:
        print(f"  (symchg.csv not loaded for merge: {e})", flush=True)
    if rename_to or recycled_split:
        merged = {}
        for sym, obs in acc.items():
            sp = recycled_split.get(sym)
            if sp:
                tgt, cutoff = sp
                pre_obs = [o for o in obs if o[0] <= cutoff]
                post_obs = [o for o in obs if o[0] > cutoff]
                if pre_obs:
                    merged.setdefault(tgt, []).extend(pre_obs)
                if post_obs:
                    merged.setdefault(sym, []).extend(post_obs)
            else:
                merged.setdefault(rename_to.get(sym, sym), []).extend(obs)
        for sym in merged:
            dd = {}
            for rec in sorted(merged[sym]):
                dd[rec[0]] = rec  # sort by date + dedup same-day overlap
            merged[sym] = [dd[k] for k in sorted(dd)]
        acc = merged
        ex = ", ".join(f"{o}->{n}" for o, n in list(rename_to.items())[:6])
        print("Merged %d renamed tickers into their current symbol (e.g. %s)" % (len(rename_to), ex), flush=True)
    # export old->current map so membership (build_membership_v2) keys on the SAME current tickers
    # the merged price series uses — otherwise renamed stocks vanish from historical backtests.
    json.dump(rename_to, open(os.path.join(HERE, "_rename_map.json"), "w"))

    # "Currently listed" universe, for the alive/industry/name tag below. Used to read this out of
    # a <script id="compressedData"> blob embedded in docs/nse-bse-dashboard.html — that page was
    # since refactored to load data from dash_slim.bin instead, so the blob hasn't existed for a
    # while and the scrape's bare except was silently leaving `cur` EMPTY. That marked EVERY symbol
    # alive=False + industry="Unknown" on every full rebuild (found 2026-08-02: RELIANCE/TCS/INFY
    # all alive=False on live data). dash_slim.bin IS the current source of truth for this now.
    # Delisted-symbol industry/name ledger (see its own _doc). Missing file is not fatal — the
    # build degrades to exactly the previous behaviour rather than aborting on a metadata nicety.
    try:
        INDUSTRY_FILLS = (json.load(open(os.path.join(HERE, "industry_fills.json"))) or {}).get("fills") or {}
        print("  industry_fills: %d delisted symbols" % len(INDUSTRY_FILLS))
    except Exception as e:
        INDUSTRY_FILLS = {}
        print("  (industry_fills unavailable:", e, ")")

    cur = {}
    try:
        slim = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "dash_slim.bin"), "rb").read()))
        for k, m in (slim.get("meta") or {}).items():
            sym = m.get("symbol") or k.split(".")[0]
            cur[sym] = {"name": m.get("name"), "industry": m.get("industry") or m.get("sector")}
    except Exception as e:
        print("  (current meta unavailable:", e, ")")
    if not cur:
        sys.exit(
            "ABORT: currently-listed universe (dash_slim.bin meta) came out EMPTY — refusing to "
            "mark every symbol dead. Fix the source before re-running (see commit that added this guard)."
        )
    alive_cut = alive_cutoff(END.isoformat())  # last bar must reach this to count as alive (§94)

    df = int(DAILY_FROM.strftime("%Y%m%d"))
    # Corporate-action ratios: bonus/split ex-dates appear as huge overnight "drops" because
    # NSE's PREV_CLOSE is NOT adjusted (verified: HDFCBANK 1:1 bonus 2025-08-26, prev_close
    # left at the raw prior close). Cash-segment circuit filters cap genuine daily moves at
    # ~20%, so a ratio far outside [0.75, 1.30] that sits within 8% of a canonical fraction
    # is a corporate action — divide it out; anything else (e.g. a real F&O-stock crash at a
    # non-fraction ratio) is kept as a genuine market move.
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
        if 0.75 <= r <= 1.30:
            return 1.0
        for f in CA_FRACS:
            if abs(r / f - 1) <= 0.08:
                return f
        return 1.0

    # OFFICIAL corporate actions (scripts/corp_actions.json, from NSE corporate-actions API).
    # 3-way priority on each ex-date drop:
    #   1) official split/bonus -> divide out the EXACT factor (fixes Adani Power's 1:5-read-as-1:4
    #      and small bonuses whose drop hides inside [0.75,1.30]);
    #   2) official demerger/scheme -> do NOT divide out (real value left the stock, e.g. Vedanta
    #      2026-04-30 773->271; dividing it out fabricated a fake 1/3 low);
    #   3) otherwise -> ca_factor inference (covers splits the API/parse missed, e.g. GRASIM).
    try:
        _ca = json.load(open(os.path.join(HERE, "corp_actions.json")))
        CA_OFF = {s: sorted(map(tuple, v)) for s, v in _ca.get("factors", {}).items()}
        NOADJ = {s: set(v) for s, v in _ca.get("noadjust", {}).items()}
        print(
            "Official corporate actions: %d split/bonus symbols, %d demerger symbols" % (len(CA_OFF), len(NOADJ)),
            flush=True,
        )
    except Exception as e:
        CA_OFF = {}
        NOADJ = {}
        print(f"  (corp_actions.json unavailable: {e} — inference only)", flush=True)
    applied_off = bad_recon = demerger_skipped = open_rescued = 0
    skip_log = []
    open_log = []
    data, meta, dead = {}, {}, 0
    for sym, obs in acc.items():
        obs.sort()
        ds, cs, ts, hr, lr, orr, vol, dv, vr = [], [], [], [], [], [], [], [], []
        adj = None
        lastWeek = None
        offlist = CA_OFF.get(sym, [])
        oi = 0
        while oi < len(offlist) and obs and offlist[oi][0] <= obs[0][0]:
            oi += 1  # ex-dates on/before the first data day already happened — nothing to adjust
        for i, (ymd, c, p, t, h, l, o, v, dlv, vw) in enumerate(obs):
            if adj is None:
                adj = c
            else:
                # Chain on ACTUAL close-to-close ratios — NOT the file's PREV_CLOSE, which NSE
                # sometimes mis-states by ±1-6% on random days (verified on CGCL), silently
                # drifting the series. Within any CA-free stretch the adjusted series equals raw
                # NSE prices exactly; on an ex-date we divide out the OFFICIAL factor (fallback:
                # inference) so 52w hi/lo and price filters stay paisa-exact.
                base = obs[i - 1][1] or 0
                r = (c / base) if base else 1.0
                f = None
                while oi < len(offlist) and offlist[oi][0] <= ymd:
                    cand = offlist[oi][1]
                    oi += 1
                    if 0.75 <= (r / cand) <= 1.30:  # implied ex-date move within circuit-ish bounds
                        f = cand
                        applied_off += 1
                    elif base and o > 0 and 0.88 <= (o / base) / cand <= 1.12:
                        # THE OPEN ARBITRATES (§87c). A real corporate action that lands on a violent
                        # day fails the close-to-close reconcile above and used to fall through to
                        # inference, which then snapped to nothing and KEPT THE WHOLE SPLIT — §87a
                        # failure mode 1. Flagship: JINDALSTEL 2008-01-21 (1:5 split on one of the
                        # worst days in Indian market history) — raw close ratio 0.1465, so
                        # r/cand = 0.7325, a hair outside the 0.75 floor; the ex-day OPEN printed at
                        # 493.50 vs a 2393.99 prev close = 0.2061, i.e. (open/prev)/factor = 1.031,
                        # dead on the adjusted basis. Circuit filters don't bound this: F&O members
                        # (JINDALSTEL since 2005-04-29) have no price band at all.
                        # Band calibrated on THIS repo's live data — 1,350 verified-applied official
                        # actions give (open/prev)/factor p5=0.9625, p50=1.0181, p95=1.0959, and 97.0%
                        # <= 1.12; §87c's independent calibration on 566 ground-truth events agrees
                        # (p5..p95 = 0.957..1.100) and puts equity crashes at >= 1.19, since a crash
                        # opens near flat and falls intraday.
                        f = cand
                        applied_off += 1
                        open_rescued += 1
                        if len(open_log) < 40:
                            open_log.append((sym, ymd, cand, round(r, 4), round((o / base) / cand, 4)))
                    else:
                        bad_recon += 1  # official ratio doesn't reconcile with the drop -> use inference
                if f is None:
                    nd = NOADJ.get(sym)
                    if nd and not (0.75 <= r <= 1.30) and any(ymd - 3 <= e <= ymd for e in nd):
                        # official demerger/scheme ex-date -> real value left the stock; keep the
                        # drop as a genuine move (do NOT divide it out).
                        demerger_skipped += 1
                        if len(skip_log) < 80:
                            skip_log.append((sym, ymd, round(r, 3)))
                        f = 1.0
                    else:
                        f = ca_factor(r)
                adj = adj * (r / f)
            if ymd >= df:
                keep = True  # daily for recent
            else:
                wk = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100).isocalendar()[:2]
                keep = wk != lastWeek
                lastWeek = wk  # weekly for old
            if keep:
                ds.append(ymd)
                cs.append(adj)
                ts.append(round(t, 1))
                raw_last = c
                # high/low/open/vwap kept as RATIOS to close (CA-adjustment cancels in the ratio) —
                # converted to EXACT adjusted ₹ below so 52w hi/lo and other filters are paisa-exact.
                hr.append((h / c) if (h >= c and c) else 1.0)
                lr.append((l / c) if (0 < l <= c and c) else 1.0)
                orr.append((o / c) if (o > 0 and c) else 1.0)
                vol.append(int(v))
                dv.append(round(dlv, 2) if dlv else 0)  # delivery % (exact; 0 = unavailable)
                vr.append((vw / c) if (vw > 0 and c) else 1.0)
        if len(ds) < 12:
            continue
        # Re-anchor (Yahoo-style adjusted prices): scale so the LAST value equals the latest RAW
        # close. EXACT high/low/open/vwap = adjusted-close x ratio, rounded to paise.
        k = (raw_last / cs[-1]) if cs[-1] else 1.0
        hs = [round(cs[i] * k * hr[i], 2) for i in range(len(ds))]
        ls = [round(cs[i] * k * lr[i], 2) for i in range(len(ds))]
        ops = [round(cs[i] * k * orr[i], 2) for i in range(len(ds))]
        vws = [round(cs[i] * k * vr[i], 2) for i in range(len(ds))]
        cs = [round(x * k, 2) for x in cs]
        data[sym] = {"d": ds, "c": cs, "t": ts, "h": hs, "l": ls, "op": ops, "v": vol, "dv": dv, "vw": vws}
        # membership AND freshness — see ALIVE_RECENCY_DAYS. `ds` is this symbol's date list, so
        # ds[-1] is its last bar; `alive_cut` is None only if END is unparseable (never here).
        alive = (sym in cur) and (alive_cut is None or ds[-1] >= alive_cut)
        dead += not alive
        # `cur` is the CURRENTLY-LISTED universe, so a delisted symbol has no row there and used to
        # fall straight through to name=<symbol>, ind="Unknown" — a survivorship gap in the metadata,
        # not a classification gap. INDUSTRY_FILLS carries BSE's own IndustryNew (the same field
        # fetch_sectors.py reads for live scrips, so the vocabulary matches by construction) for the
        # dead symbols that need it. `cur` still wins wherever it has an answer.
        _fill = INDUSTRY_FILLS.get(sym) or {}
        meta[sym] = {
            "name": (cur.get(sym) or {}).get("name") or _fill.get("name") or sym,
            "ind": ((cur.get(sym) or {}).get("industry") or _fill.get("industry") or "Unknown"),
            "alive": alive,
            "raw": round(obs[-1][1], 2),
        }  # latest RAW market close (adjusted series level can drift from market price)
        if sym in isin_of:
            meta[sym]["isin"] = isin_of[sym]
    print(
        "Stored %d symbols (%d delisted/absent today); official split/bonus applied=%d (of which %d "
        "rescued by the OPEN gate after the close-ratio reconcile failed), non-reconciling=%d, "
        "demerger/scheme drops kept (not divided out)=%d"
        % (len(data), dead, applied_off, open_rescued, bad_recon, demerger_skipped),
        flush=True,
    )
    if open_log:
        print("  OPEN-arbitrated official actions (sym, ex, factor, close-ratio, open-gate):", flush=True)
        for s, y, cf, rr, og in open_log:
            print("    %-12s %d  f=%.6f  close r=%.4f  open/prev/f=%.4f" % (s, y, cf, rr, og), flush=True)
    apply_dv_fill(data)
    if skip_log:
        print("  demerger/scheme ex-dates kept as real drops (sym, date, ratio):", flush=True)
        for s, y, rr in skip_log:
            print("    %-12s %d  ratio=%.3f" % (s, y, rr), flush=True)
    blob = gzip.compress(
        json.dumps(
            {
                "start": START.isoformat(),
                "dailyFrom": DAILY_FROM.isoformat(),
                "end": END.isoformat(),
                "meta": meta,
                "data": data,
            },
            separators=(",", ":"),
        ).encode(),
        6,
    )
    open(OUT, "wb").write(blob)
    print(f"Wrote {OUT} ({len(blob) / 1048576:.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
