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
"""BSE SME price history 2020→today (user scope: Jan-2020 on) → scripts/bse_sme_backfill.json.gz  (runbook §149).

WHY. docs/bse_prices.bin starts in 2023 and keeps only CURRENT BSE-only scrips, so every company that began on
BSE SME and later moved to the main board / NSE (INSOLATION ENERGY 543620 → NSE INA 2026-03-09) and every dead
SME scrip has no BSE-era price at all — the capex study could not form an event for them.

SOURCE. BSE's daily equity bhavcopy (download host, not the api host):
  old  www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_DDMMYY.zip   SC_CODE,SC_GROUP,CLOSE,PREVCLOSE,NO_OF_SHRS,ISIN_CODE,TRADING_DATE
  new  www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV
       FinInstrmId,SctySrs,ClsPric,PrvsClsgPric,TtlTradgVol,ISIN,TckrSymb,TradDt
SME scrips = group/series M, MT, MS on that day (point in time). A scrip that was EVER SME keeps its whole BSE
series (its later main-board days too), so a migration does not cut the history.

RULES (DATA_RUNBOOK §89f / §0): the date INSIDE the file must equal the requested date, else the file is a
re-serve and is dropped; a 403/429 or an HTML body stops the run (never read as "no file"); raw files are cached
in scripts/_bse_bhav_cache/ (gitignored) so a re-run never re-downloads; the run pauses as soon as the shared
BSE api probe (scripts/_bse_probe.log) logs OPEN — the api window belongs to the other session first.

ADJUSTMENT. BSE's PREVCLOSE is NOT ex-adjusted (measured). Splits are applied where the ISIN changes on the
ex-date; every other one-day fall >30 % is listed in `unexpl` (bonus or real crash — undecidable from prices) for
consumers to avoid until BSE's corporate-action list confirms it. Raw closes are kept beside the adjusted ones.

Run: python3 -X utf8 scripts/build_bse_sme_backfill.py --fetch [--from 20200101] [--to YYYYMMDD]
     python3 -X utf8 scripts/build_bse_sme_backfill.py --build
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import bse_headers as BH  # §181 BSE headers
import os
import sys
import io
import csv
import json
import gzip
import time
import zipfile
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get("BSE_BHAV_CACHE") or os.path.join(HERE, "_bse_bhav_cache")
MISS = os.path.join(CACHE, "_absent.json")
PROBE_LOG = os.path.join(HERE, "_bse_probe.log")
OUT = os.path.join(HERE, "bse_sme_backfill.json.gz")
OLD = "https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_%s.zip"  # DDMMYY
NEW = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_%s_F_0000.CSV"  # YYYYMMDD
OLDEST = "https://www.bseindia.com/download/BhavCopy/Equity/EQ%s_CSV.ZIP"  # DDMMYY — 2012-2016 era, no ISIN/date col
# BSE answers a file it does not serve with a 200 "Access Denied" page (14,287 B), exactly like a block. A file we
# KNOW exists is the canary: if it still downloads, the denial meant "not at this address" (measured 2026-09-23).
CANARY = "https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_220523.zip"
UA = BH.HEADERS  # honest BSE header set (§181) -- no browser impersonation
SME = {"M", "MT", "MS"}
# weekend special sessions (budget Saturdays, muhurat Sundays, DR drills) — the same list fetch_bse_bhav heals
WEEKEND = {20150228, 20161030, 20191027, 20200201, 20201114, 20231112, 20240120, 20240302, 20240518, 20241101, 20250201}
NEW_FROM = 20240701  # try the UDiFF name first from here on, the old zip before


class Blocked(RuntimeError):
    pass


def get(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
        b = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (403, 429):
            raise Blocked("HTTP %d %s" % (e.code, url))
        raise
    if b[:200].lstrip().lower().startswith((b"<!doctype", b"<html")) or b"Access Denied" in b[:2000]:
        return "DENIED"
    return b


def probe_open():
    try:
        # a real probe result line is "<YYYY-MM-DD HH:MM> IST OPEN (...)" — the header line also contains the
        # word OPEN ("OPEN = BSE answering") and falsely paused the first test run (2026-09-23)
        return any(" IST OPEN (" in ln for ln in open(PROBE_LOG))
    except OSError:
        return False


def fetch(frm, to):
    os.makedirs(CACHE, exist_ok=True)
    try:
        absent = set(json.load(open(MISS)))
    except (OSError, ValueError):
        absent = set()
    d = datetime.date(frm // 10000, frm // 100 % 100, frm % 100)
    end = datetime.date(to // 10000, to // 100 % 100, to % 100)
    got = skip = 0
    while d <= end:
        k = int(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
        if (datetime.date(k // 10000, k // 100 % 100, k % 100).weekday() >= 5 and k not in WEEKEND) or k in absent:
            continue
        if any(os.path.exists(os.path.join(CACHE, "%d.%s" % (k, ext))) for ext in ("csv", "zip")):
            continue
        if probe_open():
            print("PAUSE: BSE api probe logged OPEN — the other session's window starts first. Re-run later.")
            break
        dd = datetime.date(k // 10000, k // 100 % 100, k % 100).strftime("%d%m%y")
        order = [("csv", NEW % k), ("zip", OLD % dd), ("ozip", OLDEST % dd)]
        if k < NEW_FROM:
            order = [order[1], order[2], order[0]] if k >= 20170101 else [order[2], order[1]]
        body = ext = None
        denied = False
        for ext_, url in order:
            b = get(url)
            time.sleep(2.0)
            if b == "DENIED":
                denied = True
                continue
            if b:
                body, ext = b, ext_
                break
        if not body and denied:
            c = get(CANARY)
            time.sleep(2.0)
            if c == "DENIED" or not c:
                msg = "canary denied too — BSE download host is blocking this client"
                raise Blocked(msg)
        if not body:
            absent.add(k)
            skip += 1
            if skip % 25 == 0:
                json.dump(sorted(absent), open(MISS, "w"))
            continue
        open(os.path.join(CACHE, "%d.%s" % (k, "zip" if ext == "ozip" else ext)), "wb").write(body)
        got += 1
        if got % 50 == 0:
            print("  fetched %d files (at %d), %d absent days" % (got, k, len(absent)), flush=True)
            json.dump(sorted(absent), open(MISS, "w"))
    json.dump(sorted(absent), open(MISS, "w"))
    print("fetch done: +%d files, %d absent days, cache %d files" % (got, len(absent), len(os.listdir(CACHE)) - 1))


def rows_of(k, path):
    """[(code, group, close, prevclose, vol, isin, ticker)] for a cached day, date-checked."""
    raw = open(path, "rb").read()
    if path.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    rows = list(csv.reader(io.StringIO(raw.decode("latin1"))))
    h = [c.strip() for c in rows[0]]
    out = []
    if "SC_CODE" in h:
        ix = {c: h.index(c) for c in ("SC_CODE", "SC_GROUP", "CLOSE", "PREVCLOSE", "NO_OF_SHRS", "SC_NAME")}
        isin_i = h.index("ISIN_CODE") if "ISIN_CODE" in h else None
        td = h.index("TRADING_DATE") if "TRADING_DATE" in h else None
        for r in rows[1:]:
            if len(r) < len(h) - 3:
                continue  # a record broken across lines (newline inside a name): 2 rows in 2020-26, skipped
            if td is not None and len(r) > td and r[td].strip():
                try:
                    if int(datetime.datetime.strptime(r[td].strip(), "%d-%b-%y").strftime("%Y%m%d")) != k:
                        return None  # a re-served day: drop the file
                except ValueError:
                    pass
            try:
                float(r[ix["CLOSE"]] or 0)
                float(r[ix["PREVCLOSE"]] or 0)
                float(r[ix["NO_OF_SHRS"]] or 0)
            except ValueError:
                continue
            out.append(
                (
                    r[ix["SC_CODE"]].strip(),
                    r[ix["SC_GROUP"]].strip(),
                    float(r[ix["CLOSE"]] or 0),
                    float(r[ix["PREVCLOSE"]] or 0),
                    int(float(r[ix["NO_OF_SHRS"]] or 0)),
                    (r[isin_i].strip() if isin_i is not None and len(r) > isin_i else ""),
                    r[ix["SC_NAME"]].strip(),
                )
            )
    else:
        ix = {
            c: h.index(c)
            for c in (
                "FinInstrmId",
                "SctySrs",
                "ClsPric",
                "PrvsClsgPric",
                "TtlTradgVol",
                "ISIN",
                "TckrSymb",
                "TradDt",
                "FinInstrmTp",
            )
        }
        for r in rows[1:]:
            if len(r) <= ix["TradDt"] or r[ix["FinInstrmTp"]] != "STK":
                continue
            if int(r[ix["TradDt"]].replace("-", "")) != k:
                return None
            out.append(
                (
                    r[ix["FinInstrmId"]].strip(),
                    r[ix["SctySrs"]].strip(),
                    float(r[ix["ClsPric"]] or 0),
                    float(r[ix["PrvsClsgPric"]] or 0),
                    int(float(r[ix["TtlTradgVol"]] or 0)),
                    r[ix["ISIN"]].strip(),
                    r[ix["TckrSymb"]].strip(),
                )
            )
    return out


def build():
    ser, days, dropped = build_series()
    blob = json.dumps(
        {"built": datetime.date.today().isoformat(), "days": days, "dropped_reserved": dropped, "series": ser},
        separators=(",", ":"),
    ).encode()
    open(OUT, "wb").write(gzip.compress(blob, 9))
    print("build: %d day files (%d re-served dropped), %d scrips ever on SME, %s" % (days, dropped, len(ser), OUT))


def build_series(codes=None):
    """{code: series} from the cache — every scrip EVER on SME (default), or exactly `codes` (a set of scripcodes,
    any group), or "ALL" scrips (build_bse_sme_prepend --mainboard). Returns (series, day files used, re-served files dropped)."""
    files = sorted(f for f in os.listdir(CACHE) if f[:8].isdigit())
    ever, days, dropped = (None if codes == "ALL" else set(codes or ())), [], 0
    prev_sig = None
    for f in files:
        k = int(f[:8])
        rs = rows_of(k, os.path.join(CACHE, f))
        if rs is None:
            dropped += 1
            continue
        sig = hash(tuple(rs))
        if sig == prev_sig:
            dropped += 1
            continue  # identical to the previous day = a re-served file
        prev_sig = sig
        days.append((k, rs))
        if codes is None:
            ever.update(code for code, g, *_ in rs if g in SME)
    ser = {}
    for k, rs in days:
        for code, g, c, _pc, v, isin, tk in rs:
            if (ever is not None and code not in ever) or c <= 0:
                continue
            s = ser.setdefault(code, {"d": [], "rc": [], "isd": [], "v": [], "g": [], "isin": isin, "tk": tk})
            s["d"].append(k)
            s["rc"].append(c)
            s["isd"].append(isin)
            s["v"].append(v)
            s["g"].append(g)
            if isin:
                s["isin"] = isin
            s["tk"] = tk or s["tk"]
    return adjust_series(ser), len(days), dropped


def adjust_series(ser):
    """In place: add c (adjusted close), splits, unexpl, first_sme, last_sme to each series {d, rc, isd, v, g, isin, tk};
    drops isd/g. Shared by build_series() and scripts/bse_sme_ipo_px.py (the BSE SME IPO price ledger) so the two
    can never adjust differently."""
    # ADJUSTMENT (measured 2026-09-23): BSE's PREVCLOSE is NEVER ex-adjusted in these files (0 of 198 one-day
    # drops >30% carried an adjusted prev close), so it cannot find corporate actions. What IS reliable:
    #   * a face-value SPLIT changes the ISIN on the ex-date (INA 24-Jan-2025 INE0LGX01016 -> ...01024, 2,940.2 ->
    #     296.95) -> factor = the standard split ratio nearest the price ratio, only when within 25 %;
    #   * everything else (bonus vs a real crash) is NOT decidable from prices -> the day is listed in `unexpl`
    #     and consumers must not measure a return across it until BSE's corporate-action list confirms it.
    SPLITS = (2, 2.5, 4, 5, 10, 20, 25, 50, 100)
    n_split = n_unexpl = 0
    for s in ser.values():
        mult = [1.0] * len(s["d"])
        cum = 1.0
        unexpl = []
        splits = []
        for i in range(len(s["d"]) - 1, 0, -1):
            mult[i] = cum
            c0, c1 = s["rc"][i - 1], s["rc"][i]
            ratio = c0 / c1 if c1 > 0 else 0
            isin_chg = bool(s["isd"][i - 1] and s["isd"][i] and s["isd"][i - 1] != s["isd"][i])
            if isin_chg and ratio > 1.3:
                f = min(SPLITS, key=lambda x: abs(ratio / x - 1))
                if abs(ratio / f - 1) <= 0.25:
                    cum /= f
                    splits.append([s["d"][i], f])
                    n_split += 1
                    continue
            if ratio > 1 / 0.7:
                unexpl.append([s["d"][i], round(ratio, 3)])
                n_unexpl += 1
        mult[0] = cum
        s["c"] = [round(c * m, 4) for c, m in zip(s["rc"], mult, strict=False)]
        s["splits"] = sorted(splits)
        s["unexpl"] = sorted(unexpl)
        s["first_sme"] = next((d for d, g in zip(s["d"], s["g"], strict=False) if g in SME), None)
        s["last_sme"] = next((d for d, g in zip(reversed(s["d"]), reversed(s["g"]), strict=False) if g in SME), None)
        del s["isd"], s["g"]
    print(
        "adjust: %d ISIN-confirmed splits applied, %d unexplained one-day drops >30%% flagged (bonus or crash — "
        "needs BSE corporate actions)" % (n_split, n_unexpl)
    )
    return ser


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--fetch" in a:
        frm = int(a[a.index("--from") + 1]) if "--from" in a else 20200101
        to = int(a[a.index("--to") + 1]) if "--to" in a else int(datetime.date.today().strftime("%Y%m%d"))
        try:
            fetch(frm, to)
        except Blocked as e:
            print(f"STOPPED — BSE blocked this client: {e}")
            sys.exit(2)
    if "--build" in a:
        build()
