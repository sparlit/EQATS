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
"""Build scripts/sme_backfill.json.gz — the NSE SME-platform (Emerge) price history that
docs/sf_stock_data.bin never held. DATA_RUNBOOK §145.

WHY THIS EXISTS
  build_sf_data.parse_rows kept only the main-board cash series ("EQ","BE","BZ") — the SME
  platform's series SM (rolling), ST (trade-for-trade) and SZ (surveillance) were dropped on
  the floor, so no SME listing (SUNLITE, 571 symbols on 2026-09-22) had a price series, a
  stock page, a search-index row or a dashboard row. Flipping the filter fixes tomorrow; the
  daily updater only ever appends days after the bin's `end`, so the history since the
  platform's first listing (THEJO, 2012-09-14) rides in on this ledger, which
  update_sf_data.insert_sme_history() applies to the release-asset bin (idempotent — the same
  pattern as bz_backfill.json.gz / weekend_sessions.json.gz).

METHOD (every number measured, nothing inferred — CLAUDE.md)
  1. --scan A B      every NSE daily bhavcopy in range; keep every SM/ST/SZ row in full, plus
                     close/prev_close of every EQ/BE/BZ row (anchors for names that later moved
                     to the main board). Cached per day under scripts/_sme_scan/ (gitignored);
                     only a confirmed 404 from BOTH urls is cached as .miss, so a rate-limited
                     run just retries later. The date INSIDE the file decides (§89f): a file
                     stamped with another date is NSE re-serving the prior session and is skipped.
  2. --build         assemble one adjusted series per symbol exactly the way build_sf_data.main
                     does (chain close/close ratios; official split/bonus factors from
                     corp_actions.json when present, else the CA_FRACS inference ladder;
                     re-anchor so the last adjusted close == the last RAW close; turnover
                     normalised to ₹ LACS whatever the day's file carried — the old zip's
                     TOTTRDVAL is rupees, §88a). Same-ISIN symbols merge under the
                     latest-trading ticker (a rename), like the full build.
       Then, against the bin (--bin, default the release asset in docs/):
       · symbol absent from the bin           -> "create": the whole series + meta
       · symbol present, first bin bar AFTER
         the last ledger bar                  -> "prepend" onto that key (an SME name that
                                                migrated to the main board), anchored on the
                                                bin's first bar: scale = stored_close /
                                                raw_close that day, and an EXIT CONTROL — the
                                                ledger's last raw close must equal that day's
                                                PREV_CLOSE within 2 %, else the block is
                                                DROPPED with its measured reason (never a guess).
       · symbol present under a DIFFERENT
         ISIN, different ISSUER (isin[:7])    -> a recycled ticker: skipped and named. (Same
                                                issuer = a face-value change minted a new
                                                series; the PREV_CLOSE control adjudicates.)
       · symbol present and overlapping       -> already covered: skipped.
  3. --verify        re-open the ledger and print per-bucket counts + spot checks.

LEDGER FORMAT
  {"built": ISO, "scanned": [A, B], "create": {SYM: {"bars": [[ymd, c, t, h, l, op, v, dv, vw]…],
   "meta": {"name", "isin", "ind", "sme": true}}},
   "prepend": {SYM: {"target": BINKEY, "bars": […], "anchor": {"ymd", "raw", "prev"}}}}
  `bars` are final values on the series' OWN adjustment scale (create) or on the raw scale of
  their last day (prepend — insert_sme_history rescales onto the bin key's level).

RUN
  python3 -X utf8 scripts/build_sme_backfill.py --scan 2012-09-01 2026-09-21   # ~45 min, resumable
  python3 -X utf8 scripts/build_sme_backfill.py --build [--bin PATH]
  python3 -X utf8 scripts/build_sme_backfill.py --verify
"""
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
CACHE = os.path.join(HERE, "_sme_scan")
OUT = os.path.join(HERE, "sme_backfill.json.gz")
BIN = os.path.join(ROOT, "docs", "sf_stock_data.bin")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
SME_SERIES = ("SM", "ST", "SZ")
MAIN_SERIES = ("EQ", "BE", "BZ")
local = threading.local()
FAILED = []


# ---------------------------------------------------------------- fetch layer (build_bz_backfill twin)
def jar():
    j = http.cookiejar.CookieJar()
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
        op.open(
            urllib.request.Request("https://www.nseindia.com/", headers={"User-Agent": UA}),
            timeout=20,
        ).read()
    except Exception:
        pass
    return j


def _get(url, j, timeout=45):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"}
    )
    with op.open(req, timeout=timeout) as r:
        return r.read()


def _urls(d):
    ddmmyyyy = d.strftime("%d%m%Y")
    new = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
    old = (
        "https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip"
        % (d.year, MON[d.month - 1], d.day, MON[d.month - 1], d.year)
    )
    return [new, old] if d.year >= 2020 else [old, new]


def _file_date(hdr, rows):
    """The trading date INSIDE the file — sec_bhavdata_full `DATE1`, old zip `TIMESTAMP` (§89f)."""
    col = None
    for n in ("DATE1", "TIMESTAMP"):
        if n in hdr:
            col = hdr.index(n)
            break
    if col is None:
        return None
    for r in rows[1:]:
        if len(r) > col and r[col].strip():
            s = r[col].strip()
            for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%b-%y"):
                try:
                    return datetime.datetime.strptime(s, fmt).date().isoformat()
                except ValueError:
                    pass
            return None
    return None


def _parse(text):
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
    iC, iP, iT = (
        idx("CLOSE_PRICE", "CLOSE"),
        idx("PREV_CLOSE", "PREVCLOSE"),
        idx("TURNOVER_LACS", "TOTTRDVAL"),
    )
    iH, iL, iO = idx("HIGH_PRICE", "HIGH"), idx("LOW_PRICE", "LOW"), idx("OPEN_PRICE", "OPEN")
    iV, iW, iD, iI = (
        idx("TTL_TRD_QNTY", "TOTTRDQTY"),
        idx("AVG_PRICE"),
        idx("DELIV_PER"),
        idx("ISIN"),
    )
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

    sme, main, seen = [], {}, 0
    for r in rows[1:]:
        if len(r) <= max(iS, iC, iSer):
            continue
        seen += 1
        sym, ser = r[iS].strip(), r[iSer].strip()
        c = num(r, iC)
        if c <= 0:
            continue
        if ser in SME_SERIES:
            dash = 0 <= iD < len(r) and r[iD].strip() == "-"
            sme.append(
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
                    num(r, iD),
                    num(r, iW),
                    (r[iI].strip() if 0 <= iI < len(r) else ""),
                    1 if dash else 0,
                ]
            )
        elif ser in MAIN_SERIES:
            main[sym] = [c, num(r, iP)]
    if seen < 300:
        return None  # a real bhavcopy carries hundreds of rows; less = error body
    return {
        "date": _file_date(hdr, rows),
        "fmt": "new" if "DATE1" in hdr else "old",
        "turnover_col": hdr[iT] if iT >= 0 else "",
        "sme": sme,
        "main": main,
    }


def fetch_day(d):
    path = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
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
                obj = _parse(text)
                if obj is not None:
                    obj["url"] = url.split("/")[-1]
                    tmp = path + ".tmp"
                    json.dump(obj, open(tmp, "w"), separators=(",", ":"))
                    os.replace(tmp, path)
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
        FAILED.append(d.isoformat())


def scan(a, b, workers=6):
    os.makedirs(CACHE, exist_ok=True)
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
    print(
        "scan %s..%s: %d days, %d to fetch, %d workers" % (a, b, len(days), len(todo), workers),
        flush=True,
    )
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(fetch_day, todo):
            done += 1
            if done % 100 == 0:
                print(
                    "  %d/%d  (%.0fs, transient failures %d)"
                    % (done, len(todo), time.time() - t0, len(FAILED)),
                    flush=True,
                )
    print(
        "scan done in %.0fs; transient failures (left uncached, re-run): %d %s"
        % (time.time() - t0, len(FAILED), FAILED[:20]),
        flush=True,
    )


# ---------------------------------------------------------------- series construction (build_sf_data twin)
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


def _chain(s, m):
    """Follow an old -> new rename map to the end of the chain (cycle-safe)."""
    seen = {s}
    while s in m and m[s] not in seen:
        s = m[s]
        seen.add(s)
    return s


def load_cache():
    """-> (days: [(ymd, obj)] in date order, misdirects, dupes). A file whose inside date differs
    from its URL date is NSE re-serving another session (§89f) and is dropped; an exact repeat of
    the previous accepted day's (sym, close) set is the same re-serve on a file with no date column."""
    files = sorted(f for f in os.listdir(CACHE) if f.endswith(".json"))
    out, misdirect, dupes, prev_sig = [], 0, 0, None
    for f in files:
        ymd = int(f[:8])
        url_date = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100).isoformat()
        try:
            obj = json.load(open(os.path.join(CACHE, f)))
        except Exception:
            continue
        if obj.get("date") and obj["date"] != url_date:
            misdirect += 1
            continue
        sig = hash(tuple((r[0], r[2]) for r in obj["sme"])) if obj["sme"] else None
        if sig is not None and sig == prev_sig:
            dupes += 1
            continue
        if sig is not None:
            prev_sig = sig
        out.append((ymd, obj))
    return out, misdirect, dupes


def names_from_nse_lists():
    """Company names + ISINs from NSE's own lists when present next to the cache (the scan does not
    carry names). scripts/_sme_scan/SME_EQUITY_L.csv and EQUITY_L.csv are optional inputs."""
    names = {}
    for fn in ("SME_EQUITY_L.csv", "EQUITY_L.csv"):
        p = os.path.join(CACHE, fn)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p, encoding="utf-8", errors="replace")):
            r = {k.strip().upper().replace(" ", "_"): (v or "").strip() for k, v in r.items()}
            s = r.get("SYMBOL")
            if s and s not in names:
                names[s] = (r.get("NAME_OF_COMPANY") or s, r.get("ISIN_NUMBER") or "")
    return names


def build(bin_path):
    days, misdirect, dupes = load_cache()
    print(
        "cache: %d session files (%d misdirects dropped, %d duplicate re-serves dropped)"
        % (len(days), misdirect, dupes),
        flush=True,
    )
    if not days:
        sys.exit("nothing scanned — run --scan first")
    # official split/bonus factors (SME board is NOT in corp_actions.json today — build_corp_actions
    # now also asks index=sme, so future runs may carry some; inference covers the rest)
    try:
        _ca = json.load(open(os.path.join(HERE, "corp_actions.json")))
        CA_OFF = {
            s: sorted((int(e[0]), e[1]) for e in v) for s, v in _ca.get("factors", {}).items()
        }
        NOADJ = {s: set(v) for s, v in _ca.get("noadjust", {}).items()}
    except Exception as e:
        CA_OFF = {}
        NOADJ = {}
        print(f"  (corp_actions.json unavailable: {e} — inference only)")
    acc, isin_of, ser_last, main_px = {}, {}, {}, {}
    for ymd, obj in days:
        lacs = obj.get("turnover_col") != "TOTTRDVAL"  # old zip = raw rupees -> lacs (§88a)
        for r in obj["sme"]:
            sym, ser, c, p, t, h, l, o, v, dlv, vw, isin, dash = r
            t_l = t if lacs else t / 1e5
            acc.setdefault(sym, []).append((ymd, c, p, round(t_l, 1), h, l, o, v, dlv, vw))
            if isin:
                isin_of[sym] = isin
            ser_last[sym] = ser
        main_px[ymd] = obj["main"]
    print(
        "SME symbols seen: %d, bars: %d, first day %d, last day %d"
        % (len(acc), sum(len(v) for v in acc.values()), days[0][0], days[-1][0]),
        flush=True,
    )
    # ISIN rename merge inside the SME set (same rule as build_sf_data: latest-trading ticker wins)
    by_isin = {}
    for sym, isin in isin_of.items():
        if sym in acc:
            by_isin.setdefault(isin, []).append(sym)
    rename_to = {}
    for isin, syms in by_isin.items():
        if len(syms) < 2:
            continue
        canon = max(syms, key=lambda s: max(o[0] for o in acc[s]))
        for s in syms:
            if s != canon:
                rename_to[s] = canon
    if rename_to:
        merged = {}
        for sym, obs in acc.items():
            merged.setdefault(rename_to.get(sym, sym), []).extend(obs)
        acc = merged
        print(
            "  merged %d renamed SME tickers: %s"
            % (
                len(rename_to),
                ", ".join("{}->{}".format(*kv) for kv in list(rename_to.items())[:8]),
            )
        )
    # the bin
    D = json.loads(gzip.decompress(open(bin_path, "rb").read()))
    data, meta = D["data"], D["meta"]
    bin_isin = {m.get("isin"): k for k, m in meta.items() if isinstance(m, dict) and m.get("isin")}
    try:
        rename = json.load(
            open(os.path.join(HERE, "_rename_map.json"), encoding="utf-8")
        )  # NSE old -> new symbol
    except Exception as e:
        rename = {}
        print(f"  (_rename_map.json unavailable: {e} — successors found by key/ISIN only)")
    bin_end = int(D["end"].replace("-", ""))
    print(
        "bin: %s end=%s symbols=%d" % (os.path.basename(bin_path), D["end"], len(data)), flush=True
    )
    names = names_from_nse_lists()
    ledger = {
        "built": datetime.date.today().isoformat(),
        "scanned": [str(days[0][0]), str(days[-1][0])],
        "create": {},
        "prepend": {},
    }
    stats = collections.Counter()
    reasons = []
    for sym in sorted(acc):
        obs = {}
        for rec in sorted(acc[sym]):
            obs[rec[0]] = rec  # same-day dedup: last (highest) wins, as the full build
        obs = [obs[k] for k in sorted(obs)]
        obs = [
            o for o in obs if o[0] <= bin_end
        ]  # bars past the bin's end belong to the daily walk
        if not obs:
            stats["empty"] += 1
            continue
        # --- adjusted series, build_sf_data.main's loop -----------------------------------
        ds, cs, ts, hr, lr, orr, vol, dv, vr = [], [], [], [], [], [], [], [], []
        # §197: NSE files a renamed security's corporate actions under its CURRENT symbol — CREATIVE's official
        # 2019-06-25 x0.5 sits under CNL — so the SME era also reads the rename successor's list (a factor still
        # applies only where the day's own close ratio matches it, below)
        offlist = CA_OFF.get(sym) or CA_OFF.get(_chain(sym, rename)) or []
        adj = None
        oi = 0
        applied = inferred = 0
        while oi < len(offlist) and offlist[oi][0] <= obs[0][0]:
            oi += 1
        for i, (ymd, c, p, t, h, l, o, v, dlv, vw) in enumerate(obs):
            if adj is None:
                adj = c
            else:
                base = obs[i - 1][1] or 0
                r = (c / base) if base else 1.0
                f = None
                while oi < len(offlist) and offlist[oi][0] <= ymd:
                    cand = offlist[oi][1]
                    oi += 1
                    if (
                        0.75 <= (r / cand) <= 1.30
                        or base
                        and o > 0
                        and 0.88 <= (o / base) / cand <= 1.12
                    ):
                        f = cand
                        applied += 1
                if f is None:
                    nd = NOADJ.get(sym)
                    if nd and not (0.75 <= r <= 1.30) and any(ymd - 3 <= e <= ymd for e in nd):
                        f = 1.0
                    elif ymd >= 20160101:
                        # §161: build_corp_actions fetches the SME board's official feed from 2016, so
                        # from then on an action NSE never filed is not an action — keep the raw move.
                        f = 1.0
                    else:
                        f = ca_factor(r)
                        if f != 1.0:
                            inferred += 1
                adj = adj * (r / f)
            ds.append(ymd)
            cs.append(adj)
            ts.append(round(t, 1))
            raw_last = c
            hr.append((h / c) if (h >= c and c) else 1.0)
            lr.append((l / c) if (0 < l <= c and c) else 1.0)
            orr.append((o / c) if (o > 0 and c) else 1.0)
            vol.append(int(v))
            dv.append(round(dlv, 2) if dlv else 0)
            vr.append((vw / c) if (vw > 0 and c) else 1.0)
        k = (raw_last / cs[-1]) if cs[-1] else 1.0
        bars = [
            [
                ds[i],
                round(cs[i] * k, 2),
                ts[i],
                round(cs[i] * k * hr[i], 2),
                round(cs[i] * k * lr[i], 2),
                round(cs[i] * k * orr[i], 2),
                vol[i],
                dv[i],
                round(cs[i] * k * vr[i], 2),
            ]
            for i in range(len(ds))
        ]
        isin = isin_of.get(sym, "")
        stats["ca_official"] += applied
        stats["ca_inferred"] += inferred
        # --- where does it go? ------------------------------------------------------------
        target = sym if sym in data else (bin_isin.get(isin) if isin else None)
        if target is None and rename.get(sym):
            # §197: the successor's bin meta often carries NO isin and NSE may have renamed it since the migration
            # (WORTH SM -> WORTH EQ 2020-08-04 -> WORTHPERI 2025-10-10), so neither test above finds it and the SME
            # era was CREATED as a key of its own — which then shadowed an unrelated BSE company trading as WORTH.
            # Follow NSE's own rename chain; the PREV_CLOSE exit control below still adjudicates the join.
            t2 = _chain(sym, rename)
            if t2 in data:
                target = t2
        if target is None:
            nm = names.get(sym, (sym, ""))
            ledger["create"][sym] = {
                "bars": bars,
                "meta": {
                    "name": nm[0],
                    "isin": isin or nm[1],
                    "ind": "Unknown",
                    "sme": True,
                    "series": ser_last.get(sym, ""),
                },
            }
            stats["create"] += 1
            stats["create_bars"] += len(bars)
            continue
        e = data[target]
        F = e["d"][0]
        t_isin = (meta.get(target) or {}).get("isin")
        if target != sym and t_isin and isin and t_isin[:7] != isin[:7]:
            stats["recycled_key"] += 1
            reasons.append(
                f"{sym}->{target}: rename target holds ISIN {t_isin}, SME rows carry {isin} — different issuer, skipped"
            )
            continue
        if target == sym and t_isin and isin and t_isin != isin:
            # Same ISSUER prefix (isin[:7], the §95 sweep's grouping) = the same company whose
            # face-value change minted a new security series (AAKASH INE087Z01016 -> ...024 at
            # its main-board move); the PREV_CLOSE exit control below still adjudicates the join.
            # A different issuer = NSE re-issued the symbol to another company -> never merged.
            if t_isin[:7] != isin[:7]:
                stats["recycled_key"] += 1
                reasons.append(
                    f"{sym}: bin key holds ISIN {t_isin}, SME rows carry {isin} — different issuer, recycled ticker, skipped"
                )
                continue
            stats["isin_changed_same_issuer"] += 1
            print(
                f"  {sym}: ISIN {isin} -> {t_isin} within issuer {isin[:7]} (face-value change at the seam) — joined on PREV_CLOSE"
            )
        if bars[-1][0] >= F:
            stats["overlap"] += 1
            reasons.append(
                "%s->%s: ledger runs to %d but bin starts %d — overlap, skipped"
                % (sym, target, bars[-1][0], F)
            )
            continue
        # the main-board row on F is filed under the symbol that traded THAT day — the SME symbol itself when the
        # rename came later (WORTH on 2020-08-04, five years before WORTHPERI)
        anc = (main_px.get(F) or {}).get(target) or (main_px.get(F) or {}).get(sym)
        if not anc:
            stats["no_anchor"] += 1
            reasons.append(
                "%s->%s: bin first bar %d has no main-board row in the scan (not a scanned day) — skipped"
                % (sym, target, F)
            )
            continue
        raw_F, prev_F = anc
        last_raw = obs[-1][1]
        if not prev_F or abs(prev_F / last_raw - 1) > 0.02:
            stats["exit_fail"] += 1
            reasons.append(
                "%s->%s: NSE PREV_CLOSE on %d = %s vs ledger last raw close %s (%d) — exit control failed, skipped"
                % (sym, target, F, prev_F, last_raw, obs[-1][0])
            )
            continue
        ledger["prepend"][sym] = {
            "target": target,
            "bars": bars,
            "anchor": {"ymd": F, "raw": raw_F, "prev": prev_F},
        }
        stats["prepend"] += 1
        stats["prepend_bars"] += len(bars)
    blob = gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), 9)
    open(OUT, "wb").write(blob)
    print(
        "wrote %s (%.2f MB): create=%d (%d bars), prepend=%d (%d bars, %d across an in-issuer ISIN change), overlap=%d, recycled=%d, no_anchor=%d, exit_fail=%d; "
        "CA official=%d inferred=%d"
        % (
            OUT,
            len(blob) / 1048576,
            stats["create"],
            stats["create_bars"],
            stats["prepend"],
            stats["prepend_bars"],
            stats["isin_changed_same_issuer"],
            stats["overlap"],
            stats["recycled_key"],
            stats["no_anchor"],
            stats["exit_fail"],
            stats["ca_official"],
            stats["ca_inferred"],
        ),
        flush=True,
    )
    for r in reasons:
        print("  SKIP " + r)


def verify():
    led = json.load(gzip.open(OUT, "rt", encoding="utf-8"))
    cr, pr = led["create"], led["prepend"]
    print(
        "ledger built %s scanned %s: create=%d prepend=%d"
        % (led["built"], led["scanned"], len(cr), len(pr))
    )
    nb = sum(len(v["bars"]) for v in cr.values())
    print("  create bars: %d" % nb)
    for s in ("SUNLITE", "THEJO", "VETO"):
        v = cr.get(s)
        if v:
            b = v["bars"]
            print(
                "  %s: %d bars %d..%d last close %s name=%r isin=%s series=%s"
                % (
                    s,
                    len(b),
                    b[0][0],
                    b[-1][0],
                    b[-1][1],
                    v["meta"]["name"],
                    v["meta"]["isin"],
                    v["meta"].get("series"),
                )
            )
    for s, v in list(pr.items())[:5]:
        b = v["bars"]
        print(
            "  prepend %s->%s: %d bars %d..%d anchor %s"
            % (s, v["target"], len(b), b[0][0], b[-1][0], v["anchor"])
        )
    bad = [
        (s, i)
        for s, v in cr.items()
        for i in range(1, len(v["bars"]))
        if v["bars"][i][0] <= v["bars"][i - 1][0]
    ]
    print("  non-monotonic dates: %d" % len(bad))


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--scan" in a:
        i = a.index("--scan")
        scan(
            datetime.datetime.strptime(a[i + 1], "%Y-%m-%d").date(),
            datetime.datetime.strptime(a[i + 2], "%Y-%m-%d").date(),
            int(a[a.index("--workers") + 1]) if "--workers" in a else 6,
        )
    elif "--build" in a:
        build(a[a.index("--bin") + 1] if "--bin" in a else BIN)
    elif "--verify" in a:
        verify()
    else:
        print(__doc__)
