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
"""Fetch NSE F&O bhavcopy (EOD derivatives) for index options/futures backtesting.

Two archive eras (both measured live 2026-08-24, runbook-style validation):
  OLD   (<= 2024-07-05): /content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DD}{MMM}{YYYY}bhav.csv.zip
        cols: INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,
              SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP
  UDIFF (>= 2024-07-08): /content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip
        cols incl: FinInstrmTp(IDO/IDF/STO/STF),TckrSymb,XpryDt,StrkPric,OptnTp,
              OpnPric,HghPric,LwPric,ClsPric,PrvsClsgPric,UndrlygPric,SttlmPric,
              OpnIntrst,ChngInOpnIntrst,TtlTradgVol

Keeps ONLY index derivatives for INDICES below. Raw per-day extracts are cached as
gzipped JSON under CACHE_DIR (kept OUT of any git tree - ~1-2KB..80KB/day) so the
store builder can re-derive without re-downloading (memory: persist raw rows).

A 200 response is NOT the file: every zip is opened and the csv parsed; failures
are recorded in _fo_fetch_log.json and retried on next run (retry the transient).

Usage:
  python3 fetch_fo_bhavcopy.py 2016-01-01 2026-08-24   # backfill (resumable)
  python3 fetch_fo_bhavcopy.py --recent 7              # last N calendar days (CI)
"""
import csv
import datetime as dt
import gzip
import io
import json
import os
import random
import sys
import time
import urllib.request
import zipfile

INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
CACHE_DIR = os.environ.get("FO_CACHE", os.path.expanduser("~/stocks-wt/fo_raw_cache"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
OLD_LAST = dt.date(2024, 7, 5)  # last old-format day (measured: 2024-07-08 old URL 404s)
UDIFF_FIRST = dt.date(2024, 7, 8)  # first UDiFF day (measured live)
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def url_for(d):
    if d <= OLD_LAST:
        m = MON[d.month - 1]
        return (
            "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d.year}/{m}/fo{d.day:02d}{m}{d.year}bhav.csv.zip"
        )
    return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def cache_path(d):
    return os.path.join(CACHE_DIR, f"{d.year}", f"{d:%m%d}.json.gz")


def parse_old(text):
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("SYMBOL") or "").strip()
        ins = (r.get("INSTRUMENT") or "").strip()
        if sym not in INDICES or ins not in ("OPTIDX", "FUTIDX"):
            continue
        try:
            exp = dt.datetime.strptime(r["EXPIRY_DT"].strip(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        rows.append(
            {
                "sym": sym,
                "ins": "OPT" if ins == "OPTIDX" else "FUT",
                "exp": exp,
                "k": float(r["STRIKE_PR"] or 0),
                "t": (r.get("OPTION_TYP") or "").strip(),
                "o": float(r["OPEN"] or 0),
                "h": float(r["HIGH"] or 0),
                "l": float(r["LOW"] or 0),
                "c": float(r["CLOSE"] or 0),
                "s": float(r["SETTLE_PR"] or 0),
                "v": int(float(r["CONTRACTS"] or 0)),
                "oi": int(float(r["OPEN_INT"] or 0)),
                "u": None,
            }
        )
    return rows


def parse_udiff(text):
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("TckrSymb") or "").strip()
        tp = (r.get("FinInstrmTp") or "").strip()
        if sym not in INDICES or tp not in ("IDO", "IDF"):
            continue
        exp = (r.get("XpryDt") or "").strip()
        if not exp:
            continue

        def f(k):
            v = (r.get(k) or "").strip()
            return float(v) if v else 0.0

        rows.append(
            {
                "sym": sym,
                "ins": "OPT" if tp == "IDO" else "FUT",
                "exp": exp,
                "k": f("StrkPric"),
                "t": (r.get("OptnTp") or "").strip(),
                "o": f("OpnPric"),
                "h": f("HghPric"),
                "l": f("LwPric"),
                "c": f("ClsPric"),
                "s": f("SttlmPric"),
                "v": int(f("TtlTradgVol")),
                "oi": int(f("OpnIntrst")),
                "u": f("UndrlygPric") or None,
            }
        )
    return rows


def fetch_day(d):
    """Returns 'ok' | 'nofile' | 'error'. Writes cache file on ok."""
    p = cache_path(d)
    if os.path.exists(p):
        return "ok"
    req = urllib.request.Request(url_for(d), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as e:
        return "nofile" if e.code == 404 else "error"
    except Exception:
        return "error"
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = z.namelist()[0]
            text = z.read(name).decode("utf-8", "replace")
    except Exception:
        return "error"  # 200 but not a zip => treat as transient
    rows = parse_old(text) if d <= OLD_LAST else parse_udiff(text)
    if not rows:
        return "error"  # parsed fine but nothing for our indices: suspicious
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.open(p, "wt") as f:
        json.dump({"date": d.isoformat(), "rows": rows}, f, separators=(",", ":"))
    return "ok"


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--recent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        end = dt.date.today()
        start = end - dt.timedelta(days=n)
    else:
        start = dt.date.fromisoformat(sys.argv[1])
        end = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date.today()
    log_p = os.path.join(CACHE_DIR, "_fo_fetch_log.json")
    log = json.load(open(log_p)) if os.path.exists(log_p) else {"nofile": [], "error": []}
    ok = new = nofile = err = 0
    d = start
    while d <= end:
        iso = d.isoformat()
        if d.weekday() >= 5 or (d > OLD_LAST and d < UDIFF_FIRST):
            d += dt.timedelta(days=1)
            continue
        if iso in log["nofile"]:  # known holiday - skip quietly
            d += dt.timedelta(days=1)
            continue
        had = os.path.exists(cache_path(d))
        r = fetch_day(d)
        if r == "ok":
            ok += 1
            if not had:
                new += 1
                time.sleep(0.35 + random.random() * 0.3)
        elif r == "nofile":
            nofile += 1
            if iso not in log["nofile"]:
                log["nofile"].append(iso)
            time.sleep(0.3)
        else:
            err += 1
            if iso not in log["error"]:
                log["error"].append(iso)
            time.sleep(2.0)
        if (ok + nofile + err) % 200 == 0:
            print(f"...{iso}  ok={ok} new={new} nofile={nofile} err={err}", flush=True)
        d += dt.timedelta(days=1)
    log["error"] = [x for x in log["error"] if not os.path.exists(cache_path(dt.date.fromisoformat(x)))]
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump(log, open(log_p, "w"), indent=1)
    print(f"DONE ok={ok} new={new} nofile(holiday)={nofile} error={err}")
    print(f"errors pending retry: {len(log['error'])}")


if __name__ == "__main__":
    main()
