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
"""Build scripts/bz_backfill.json.gz — the missing series-BZ history for docs/sf_stock_data.bin.

WHY THIS EXISTS
  build_sf_data.parse_rows kept only ("EQ","BE") until 2026-08-10, so every bar a company traded
  in series BZ (trade-for-trade + surveillance — still listed, still trading daily) was dropped on
  the floor. A stock's series simply STOPPED on the day it was penalised into BZ and resumed only
  if it was promoted back. Flipping the filter fixes tomorrow; it cannot fix yesterday, because the
  daily updater only ever appends days after the bin's `end`. This tool reads the missing bars back
  out of NSE's own daily bhavcopies and emits a ledger that update_sf_data.insert_bz_history()
  applies to the release-asset bin (idempotent, same pattern as weekend_sessions.json.gz).

  It also heals a SECOND defect the gap caused. When a stock was promoted back out of BZ, the
  updater saw one enormous "overnight" ratio across the invisible hole and ca_factor() read it as a
  split/bonus — dividing a corporate action out of history that never happened. Measured on the
  2026-08-07 bin: 21 blocks over 18 symbols sit at a scale NSE's official corporate-action feed does
  not account for (ATLASCYCLE x2/3, KERNEX x2/3, RAJRAYON x1/3, SUPREMEINF x6 and x3, TIL x2 twice,
  JYOTISTRUC x5/6, ...). Those are phantom. The ledger carries the reciprocal as `pre`.

METHOD (every number measured, nothing inferred — CLAUDE.md)
  1. Scan every NSE daily bhavcopy in range; keep every series-BZ row.       [--scan]
  2. Fetch each gap's two BOUNDARY sessions [--anchors]: the bin bar before it (whose RAW close says
     what scale the bin's history sits on) and the bin bar after it (whose PREV_CLOSE is NSE's own
     statement of what the previous session closed at).
  3. For each (symbol, contiguous block of missing bars), with P_off = the product of OFFICIAL
     split/bonus factors after L, and L = the last bin bar before the block:
       s_pre  = bin_stored_close(L) / raw_close(L)  =  P_off x P_phantom
       f_ph   = snap(s_pre / P_off) to a CA_FRACS product   -> pre = 1 / f_ph
     then TWO controls, both of which drop the block rather than ship a guess:
       entry  — the first missing bar must be a plausible one-session move off L;
       exit   — our LAST backfilled close must equal the resumption day's PREV_CLOSE to 2%. This is
                the one that adjudicates a big move at a promotion out of BZ: leaving trade-for-trade
                genuinely gaps, so the size of the move proves nothing, but PREV_CLOSE does. It is
                what catches a real split hiding in the hole (SDBL 0.200, PARASPETRO 0.100, ...).
     Every skipped block is printed with its measured reason.

OUT  scripts/bz_backfill.json.gz
  {"built","binEnd","source","blocks":{SYM:[{"from":ymd,"after":ymd,"pre":f,
                                             "bars":[[ymd,c,turn,h,l,op,v,dv,vw],...]}]}}
  `after` = the bin date this block attaches behind; `pre` = factor for the bin bars in
  (`from`, `after`] — the SEGMENT this block ends, not the whole series, because a symbol with two
  holes carries a different phantom product on each segment (A=p1*p2, B=p2, C=1). `from` is the
  PREVIOUS block's last inserted bar (0 for the first), and the bound is EXCLUSIVE so that bar is
  not scaled twice. `bars` = final values, already on the series' adjustment scale.

RUN
  python3 -X utf8 scripts/build_bz_backfill.py --scan 2002-01-01 2026-08-10   # slow, resumable
  python3 -X utf8 scripts/build_bz_backfill.py --anchors                      # ~1 file per gap
  python3 -X utf8 scripts/build_bz_backfill.py --build                        # writes the ledger
  (--bin /path/to/sf_stock_data.bin to point at a downloaded release asset; default docs/ copy.
   SCAN CACHE lives in scripts/_bz_scan/ and is gitignored — a failed fetch is NEVER cached as
   "no data", only a confirmed 404 from both URLs is, so a rate-limited run just retries later.)
"""
import bisect
import collections
import csv
import datetime
import gzip
import http.cookiejar
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "_bz_scan")
os.makedirs(CACHE, exist_ok=True)
OUT = os.path.join(HERE, "bz_backfill.json.gz")
BIN = os.path.join(ROOT, "docs", "sf_stock_data.bin")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
local = threading.local()
FAILED = []
DAILY_FROM = 20180101  # overwritten from the bin's own `dailyFrom` in build()


# ---------------------------------------------------------------- fetch layer
def jar():
    j = http.cookiejar.CookieJar()
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
        op.open(urllib.request.Request("https://www.nseindia.com/", headers={"User-Agent": UA}), timeout=20).read()
    except Exception:
        pass
    return j


def _get(url, j, timeout=45):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
    with op.open(req, timeout=timeout) as r:
        return r.read()


def _urls(d):
    ddmmyyyy = d.strftime("%d%m%Y")
    new = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
    old = "https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip" % (
        d.year,
        MON[d.month - 1],
        d.day,
        MON[d.month - 1],
        d.year,
    )
    return [new, old] if d.year >= 2020 else [old, new]


def _rows(text, keep):
    """keep(sym, ser) -> bool. Returns None when the body is not a real bhavcopy."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return None
    hdr = [h.strip().upper() for h in rows[0]]

    def idx(*ns):
        for n in ns:
            if n in hdr:
                return hdr.index(n)
        return -1

    iS, iSer = idx("SYMBOL"), idx("SERIES")
    iC, iP, iT = idx("CLOSE_PRICE", "CLOSE"), idx("PREV_CLOSE", "PREVCLOSE"), idx("TURNOVER_LACS", "TOTTRDVAL")
    iH, iL, iO = idx("HIGH_PRICE", "HIGH"), idx("LOW_PRICE", "LOW"), idx("OPEN_PRICE", "OPEN")
    iV, iW, iD = idx("TTL_TRD_QNTY", "TOTTRDQTY"), idx("AVG_PRICE"), idx("DELIV_PER")
    if iS < 0 or iC < 0 or iSer < 0:
        return None

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

    out, seen = [], 0
    for r in rows[1:]:
        if len(r) <= max(iS, iC, iSer):
            continue
        seen += 1
        sym, ser = r[iS].strip(), r[iSer].strip()
        if not keep(sym, ser):
            continue
        c = num(r, iC)
        if c <= 0:
            continue
        dlv = num(r, iD)
        if ser in ("BE", "BZ") and iD >= 0 and dlv == 0:
            dlv = 100.0  # T2T: DELIV_* printed as '-'
        out.append(
            [
                sym,
                ser,
                c,
                num(r, iP),
                num(r, iT),
                num(r, iH, c),
                num(r, iL, c),
                num(r, iO, c),
                num(r, iV),
                dlv,
                num(r, iW),
            ]
        )
    # a real bhavcopy always carries hundreds of rows; anything smaller is an error body
    return out if seen >= 300 else None


def fetch_day(d, keep, path):
    """Cache one day. Only a confirmed 404 from BOTH urls is cached as 'no session' (.miss);
    every other failure leaves the day uncached so a later run retries it."""
    miss = path[:-5] + ".miss"
    if os.path.exists(path) or os.path.exists(miss):
        return
    saw404 = set()
    urls = _urls(d)
    for attempt in range(3):
        if not hasattr(local, "jar") or attempt:
            local.jar = jar()
        for url in urls:
            try:
                blob = _get(url, local.jar)
                if url.endswith(".zip"):
                    z = zipfile.ZipFile(io.BytesIO(blob))
                    text = z.read(z.namelist()[0]).decode("utf-8", "replace")
                else:
                    text = blob.decode("utf-8", "replace")
                rows = _rows(text, keep)
                if rows is not None:
                    json.dump(rows, open(path, "w"))
                    return
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    saw404.add(url)
            except Exception:
                pass
        time.sleep(1.5 * (attempt + 1))
    if len(saw404) == len(urls):
        open(miss, "w").write("404")
    else:
        FAILED.append(os.path.basename(path)[:8])


def scan(a, b, workers=3):
    days, d = [], a
    while d <= b:
        days.append(d)
        d += datetime.timedelta(days=1)
    todo = [
        x
        for x in days
        if not os.path.exists(os.path.join(CACHE, x.strftime("%Y%m%d") + ".json"))
        and not os.path.exists(os.path.join(CACHE, x.strftime("%Y%m%d") + ".miss"))
    ]
    print("scan %s..%s: %d days, %d to fetch" % (a, b, len(days), len(todo)), flush=True)

    def keep(sym, ser):
        return ser == "BZ"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(lambda x: fetch_day(x, keep, os.path.join(CACHE, x.strftime("%Y%m%d") + ".json")), todo):
            done += 1
            if done % 100 == 0:
                print("  %d/%d (transient failures %d)" % (done, len(todo), len(FAILED)), flush=True)
    print("scan done; transient failures (left uncached, re-run): %d" % len(FAILED), flush=True)


# ---------------------------------------------------------------- analysis layer
# The exact ladder update_sf_data.ca_factor() picks from, and its 8% acceptance window. A phantom
# factor baked into the bin is always one of these, or a product of them (one per ex-date it fired
# on across the invisible hole), so the correction is an EXACT reciprocal, never a measured ratio.
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
_CAND = sorted({1.0} | set(CA_FRACS) | {round(a * b, 10) for a in CA_FRACS for b in CA_FRACS})


def _snap(x, tol=0.08):
    """-> the CA_FRACS product `x` is within `tol` of, or None when nothing matches."""
    if x <= 0:
        return None
    best, err = None, tol
    for c in _CAND:
        e = abs(x / c - 1)
        if e < err:
            best, err = c, e
    return best


def bin_calendar(D):
    """The trading calendar, taken from the BIN itself: the union of dates of stocks that trade
    every single session. It has to come from the bin and not from our own fetch, for two reasons.
    NSE's per-day URL re-serves the PRIOR session's file on holidays and weekends, so a naive
    "every day we downloaded" calendar contains Sundays — RAJESHEXPO's block starts 2025-12-26 and
    a phantom 2025-12-25 sat in front of it, which broke the adjacency test and dropped the symbol
    the whole exercise started from. And "the session before day X" must mean the same thing here
    as it does in the file we are splicing into, or the two grids disagree at every join."""
    cal = set()
    for r in ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "ITC", "SBIN", "LT"):
        e = D["data"].get(r)
        if e:
            cal.update(e["d"])
    return sorted(cal)


def load_scan(cal=None):
    """-> ({ymd: {sym: row}} for days that have BZ rows, the ordered list of those days).

    `cal` (the bin's own session grid) filters out NSE's holiday re-serves: a Sunday file is a copy
    of Friday's, and inserting its rows would fabricate a session the exchange never held.

    NSE's per-day URL serves the PRIOR session's file on some holidays; two real sessions are never
    byte-identical across the whole BZ list, so an exact duplicate of the previous accepted day is
    that misdirect and is dropped (same guard build_sf_data uses)."""
    days = sorted(
        int(f[:8])
        for f in os.listdir(CACHE)
        if f.endswith(".json") and not f.endswith(".anchor.json") and f[:8].isdigit()
    )
    calset = set(cal or [])
    out, sessions, prev, dropped = {}, [], None, 0
    for y in days:
        if calset and y not in calset:
            dropped += 1
            continue
        rows = [r for r in json.load(open(os.path.join(CACHE, "%d.json" % y))) if r[1] == "BZ"]
        if not rows:
            continue
        sig = tuple(sorted((r[0], r[2]) for r in rows))
        if sig == prev:
            continue
        prev = sig
        out[y] = {r[0]: r for r in rows}
        sessions.append(y)
    if dropped:
        print("  scan: %d fetched days are not sessions in the bin's calendar — dropped" % dropped)
    return out, sessions


def load_bin(path):
    return json.loads(gzip.decompress(open(path, "rb").read()))


def gaps(D, byday, sessions, cal):
    """-> [(sym, after_ymd, [ (ymd,row), ... ]) ] contiguous blocks of BZ bars the bin lacks."""
    data = D["data"]
    per = collections.defaultdict(list)
    for y in sessions:
        for sym, r in byday[y].items():
            per[sym].append((y, r))
    out, orphan = [], collections.Counter()
    for sym, lst in per.items():
        e = data.get(sym)
        if not e:
            orphan[sym] += len(lst)
            continue
        ds = e["d"]
        have = set(ds)
        missing = [(y, r) for y, r in lst if y not in have]
        if not missing:
            continue
        # A block is a maximal run of missing bars with NO bin bar between them. Do NOT split on
        # non-consecutive SESSIONS: a thin BZ stock trades on a minority of days, so consecutive
        # bars are routinely weeks apart and a session-adjacency split shattered ACROPETAL-class
        # names into hundreds of one-bar blocks, every one of them unanchorable.
        block = []
        for y, r in missing:
            if block:
                k = bisect.bisect_right(ds, block[-1][0])
                if k < len(ds) and ds[k] < y:  # the bin has a bar inside — real boundary
                    out.append((sym, block))
                    block = []
            block.append((y, r))
        if block:
            out.append((sym, block))
    return out, orphan


def build(D, byday, sessions, cal, ca_path):
    data = D["data"]
    global DAILY_FROM
    DAILY_FROM = int((D.get("dailyFrom") or "2018-01-01").replace("-", ""))
    try:
        _ca = json.load(open(ca_path))
        FAC = {s: {int(e[0]): e[1] for e in v} for s, v in _ca.get("factors", {}).items()}
    except Exception as ex:
        FAC = {}
        print(f"  (corp_actions.json unavailable: {ex})")
    blocks, orphan = gaps(D, byday, sessions, cal)
    spos = {y: i for i, y in enumerate(cal)}
    anchors = (
        json.load(open(os.path.join(CACHE, "_anchors.json")))
        if os.path.exists(os.path.join(CACHE, "_anchors.json"))
        else {}
    )

    ledger = collections.defaultdict(list)
    skipped, phantom, nbars = [], [], 0
    via_n = collections.Counter()
    exitchk = collections.Counter()
    prev_end = {}  # sym -> last bar date of the previous block, so `pre` scopes to ONE segment
    for sym, block in sorted(blocks, key=lambda x: (x[0], x[1][0][0])):
        e = data[sym]
        ds = e["d"]
        cs = e["c"]
        y0 = block[0][0]
        i = bisect.bisect_left(ds, y0)
        if i == 0:
            skipped.append((sym, y0, "no bin bar before the block"))
            continue
        L = ds[i - 1]
        stored = cs[i - 1]
        # RAW close on L: the anchor file (authoritative) or, when the block starts the very next
        # session, the first BZ row's own PREV_CLOSE. Never a guess — no anchor means skip.
        # RAW close on L. Authoritative route: the anchor file — day L's own bhavcopy row.
        # The only accepted fallback is the first BZ row's PREV_CLOSE, and ONLY when that row is the
        # very next SESSION after L, where PREV_CLOSE provably refers to L. It is not usable across a
        # longer stretch: a security that stops trading altogether can come back at a price NSE has
        # re-established, so PREV_CLOSE is then somebody else's number. HDIL is the proof — bin ends
        # 2020-03-02 at 2.20, it then vanishes from the bhavcopy entirely for years, and its first BZ
        # row prints PREV_CLOSE 4.30. Reading that as "scale 0.5116" would have invented a corporate
        # action out of a suspension.
        raw = (anchors.get(sym) or {}).get(str(L))
        if isinstance(raw, list):
            raw = raw[0]
        via = "anchor"
        if raw is None:
            j0 = spos.get(y0, -1)
            if j0 > 0 and cal[j0 - 1] == L and block[0][1][3] > 0:
                raw = block[0][1][3]
                via = "prevclose"
        if not raw or raw <= 0:
            skipped.append((sym, y0, "no raw close for anchor day %d" % L))
            continue
        if not stored or stored <= 0:
            # a 0.00 stored close (sub-paise penny, rounded away) gives no scale to reconcile against
            skipped.append((sym, y0, "bin close on anchor day %d is %r" % (L, stored)))
            continue
        s_pre = stored / raw
        # THE SCALE MODEL. The pipeline stores  stored(t) = raw(t) x PROD{f : ex > t}  over every
        # factor it ever applied, official or inferred, and re-anchors so the final bar is raw. So
        #     s_pre = stored(L)/raw(L) = P_official(>L) x P_phantom(>L)
        # and the factor that undoes ONLY the phantom part is  pre = P_official(>L) / s_pre.
        # P_official must span every official ex-date after L — NOT just the ones inside this block.
        # Scoping it to the block is what made SDBL read as phantom: its 0.1950 scale is exactly the
        # 0.5 (2020-10-15) x 0.4 (2024-05-24) pair, both of which fall after its block ends.
        off = {ex: f for ex, f in (FAC.get(sym) or {}).items() if ex > L}
        p_off = 1.0
        for f in off.values():
            p_off *= f
        # What the bin actually holds is not the measured ratio — it is whatever ca_factor() returned,
        # and ca_factor only ever returns a member of CA_FRACS (or a product of them, one per ex-date
        # it fired on). So SNAP to that exact value instead of dividing by a measurement: the measured
        # ratio carries PREV_CLOSE noise (NSE mis-states that column by ~1-6% on random days), and
        # JYOTISTRUC shows what the noise costs — measured 0.8228 against a baked-in 5/6 = 0.8333, so
        # the un-snapped correction would have left the series 1.3% wrong forever.
        # A residual that snaps to 1.0 means nothing phantom was applied. A residual that snaps to
        # NOTHING means we cannot say what is in there — skip the block rather than invent a factor.
        want = s_pre / p_off
        f_ph = _snap(want)
        if f_ph is None:
            skipped.append((sym, y0, f"scale {s_pre:.4f} (official {p_off:.4f}) matches no ca_factor product"))
            continue
        pre = 1.0 / f_ph

        # CONTINUITY CONTROL — the claim "this block belongs here at this scale" has two joins, and
        # both must land inside a plausible one-session move. A corporate action our official feed is
        # missing would otherwise be laundered into the series as a phantom correction.
        def _p(after):  # official product above a date
            q = 1.0
            for ex, fx in off.items():
                if ex > after:
                    q *= fx
            return q

        lo, hi = 0.5, 2.0  # generous: circuit bands are +-20%, a T2T name can gap
        r_in = (block[0][1][2] * _p(block[0][0])) / (raw * p_off)
        if not (lo <= r_in <= hi):
            skipped.append((sym, y0, "entry join implausible (%.3f) — unexplained action at %d" % (r_in, L)))
            continue
        j_after = bisect.bisect_right(ds, block[-1][0])
        if j_after < len(ds):  # the series resumes -> the far join has to reconcile too
            r_out = cs[j_after] / (block[-1][1][2] * _p(block[-1][0]))
            # NSE's own PREV_CLOSE on the resumption day is the decisive test, when we have it:
            # it must equal our last backfilled close. A big MOVE there proves nothing (a stock
            # leaving trade-for-trade genuinely gaps), but a PREV_CLOSE that disagrees does — it
            # means something happened inside the hole that this ledger cannot see.
            xr = (anchors.get(sym) or {}).get(str(ds[j_after]))
            xp = xr[1] if isinstance(xr, list) and len(xr) > 1 else None
            if xp and xp > 0:
                d_out = (block[-1][1][2] * _p(block[-1][0])) / xp
                if not (0.98 <= d_out <= 1.02):
                    skipped.append(
                        (
                            sym,
                            y0,
                            "exit PREV_CLOSE %.2f on %d disagrees with our last bar "
                            "(ratio %.3f)" % (xp, ds[j_after], d_out),
                        )
                    )
                    continue
                exitchk["verified"] += 1
            else:
                exitchk["unverified"] += 1
                if not (lo <= r_out <= hi):
                    skipped.append(
                        (
                            sym,
                            y0,
                            "exit join implausible (%.3f) at %d, no PREV_CLOSE to arbitrate" % (r_out, ds[j_after]),
                        )
                    )
                    continue
        # The bin stores WEEKLY samples before `dailyFrom` and daily after (build_sf_data), so a
        # pre-2018 block must be thinned the same way or the backfill would leave those symbols
        # denser than every other series in the file. Same rule the rebuild uses: first session of
        # each ISO week — and never a week the bin already has a bar in.
        binweeks = {datetime.date(x // 10000, x // 100 % 100, x % 100).isocalendar()[:2] for x in ds if x < DAILY_FROM}
        block2, seenwk = [], set()
        for y, r in block:
            if y >= DAILY_FROM:
                block2.append((y, r))
                continue
            wk = datetime.date(y // 10000, y // 100 % 100, y % 100).isocalendar()[:2]
            if wk in seenwk or wk in binweeks:
                continue
            seenwk.add(wk)
            block2.append((y, r))
        if not block2:
            continue
        block = block2
        bars = []
        for y, r in block:
            f = _p(y)  # a bar sits above every official ex-date that follows it
            c = r[2] * f
            bars.append(
                [
                    y,
                    round(c, 2),
                    round(r[4], 1),
                    round(max(r[5], r[2]) * f, 2),
                    round((min(r[6], r[2]) if r[6] > 0 else r[2]) * f, 2),
                    round((r[7] if r[7] > 0 else r[2]) * f, 2),
                    int(r[8]),
                    round(r[9], 2) if r[9] else 0,
                    round((r[10] if r[10] > 0 else r[2]) * f, 2),
                ]
            )
        via_n[via] += 1
        if f_ph != 1.0:  # recorded only once the block SURVIVES both continuity controls
            phantom.append((sym, L, round(s_pre, 4), round(p_off, 4), round(pre, 6), len(bars), via))
        ledger[sym].append({"from": prev_end.get(sym, 0), "after": L, "pre": round(pre, 6), "bars": bars})
        prev_end[sym] = block[-1][0]
        nbars += len(bars)

    print("\nblocks: %d over %d symbols; bars %d" % (sum(len(v) for v in ledger.values()), len(ledger), nbars))
    print(
        "symbols in BZ that have no series in the bin at all (not backfillable here): %d (%d bars)"
        % (len(orphan), sum(orphan.values()))
    )
    if orphan:
        print("   " + ", ".join("%s:%d" % kv for kv in orphan.most_common(12)))
    print("\nPHANTOM corporate actions undone (%d):" % len(phantom))
    print(
        "   %-12s %10s %9s %9s %8s %6s %s" % ("SYM", "anchorDay", "scaleWas", "official", "pre", "bars", "anchoredBy")
    )
    for p in phantom:
        print("   %-12s %10d %9.4f %9.4f %8.4f %6d %s" % p)
    print(
        "\nentry anchor: %d blocks off the day's own bhavcopy row, %d off PREV_CLOSE"
        % (via_n.get("anchor", 0), via_n.get("prevclose", 0))
    )
    print(
        "exit join: %d blocks PROVEN contiguous by the resumption day's PREV_CLOSE, %d unverified "
        "(bounds-checked only)" % (exitchk.get("verified", 0), exitchk.get("unverified", 0))
    )
    if skipped:
        print("\nSKIPPED blocks (anchor not established — reported, never guessed): %d" % len(skipped))
        for s in skipped[:30]:
            print("   %-12s %10d  %s" % s)
    return {
        "built": datetime.date.today().isoformat(),
        "binEnd": D.get("end"),
        "source": "NSE daily bhavcopy (sec_bhavdata_full / cm<DDMON YYYY>bhav)",
        "blocks": dict(sorted(ledger.items())),
    }


def anchor_pass(D, byday, sessions, cal, workers=3):
    """Fetch each gap's two boundary sessions.

    ENTRY anchor = the bin bar right before the block: its RAW close says what scale the bin's own
    history is sitting on. EXIT anchor = the bin bar right after the block (when the series resumes):
    we want that day's PREV_CLOSE, which is NSE's own statement of what the previous session closed
    at. If it equals our last backfilled bar, the splice is provably contiguous with the exchange's
    bookkeeping; if it does not, something happened in the hole that we cannot see, and the block is
    dropped rather than shipped. This is the control that adjudicates a big move at a promotion out
    of BZ — coming off trade-for-trade genuinely gaps, so the size of the move proves nothing by
    itself, but PREV_CLOSE does."""
    blocks, _ = gaps(D, byday, sessions, cal)
    data = D["data"]
    need = collections.defaultdict(set)  # ymd -> {sym}
    for sym, block in blocks:
        ds = data[sym]["d"]
        i = bisect.bisect_left(ds, block[0][0])
        if i:
            need[ds[i - 1]].add(sym)
        k = bisect.bisect_right(ds, block[-1][0])
        if k < len(ds):
            need[ds[k]].add(sym)
    print("boundary days to fetch: %d (for %d gap blocks)" % (len(need), len(blocks)), flush=True)
    got = {}
    ap = os.path.join(CACHE, "_anchors.json")
    if os.path.exists(ap):
        got = json.load(open(ap))
    todo = [y for y in sorted(need) if not os.path.exists(os.path.join(CACHE, "%d.anchor.json" % y))]

    def one(y):
        d = datetime.date(y // 10000, y // 100 % 100, y % 100)
        want = need[y]
        fetch_day(d, lambda sym, ser: sym in want, os.path.join(CACHE, "%d.anchor.json" % y))

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(one, todo):
            done += 1
            if done % 25 == 0:
                print("  %d/%d" % (done, len(todo)), flush=True)
    for y in sorted(need):
        p = os.path.join(CACHE, "%d.anchor.json" % y)
        if not os.path.exists(p):
            continue
        for r in json.load(open(p)):
            got.setdefault(r[0], {})[str(y)] = [r[2], r[3]]  # [close, prev_close]
    json.dump(got, open(ap, "w"))
    print("boundary rows resolved for %d symbols (transient failures %d)" % (len(got), len(FAILED)), flush=True)


def main():
    argv = sys.argv[1:]
    binp = BIN
    if "--bin" in argv:
        binp = argv[argv.index("--bin") + 1]
    if "--scan" in argv:
        k = argv.index("--scan")
        a = datetime.datetime.strptime(argv[k + 1], "%Y-%m-%d").date()
        b = datetime.datetime.strptime(argv[k + 2], "%Y-%m-%d").date()
        scan(a, b)
        return 0
    D = load_bin(binp)
    cal = bin_calendar(D)
    byday, sessions = load_scan(cal)
    print(
        "bin %s (end %s, %d symbols); bin calendar %d sessions (%d..%d), %d scan days with BZ rows"
        % (binp, D.get("end"), len(D["data"]), len(cal), cal[0] if cal else 0, cal[-1] if cal else 0, len(sessions))
    )
    if "--anchors" in argv:
        anchor_pass(D, byday, sessions, cal)
        return 0
    led = build(D, byday, sessions, cal, os.path.join(HERE, "corp_actions.json"))
    if not led["blocks"]:
        print("nothing to write")
        return 1
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"))
    print(f"\nWrote {OUT} ({os.path.getsize(OUT) / 1048576:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
