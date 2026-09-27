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
"""One-off backfill of docs/fii_fo_lots.json + the "lf" lot factor on docs/fii_fo.json (2026-09-25).

For every fii_fo row: download that day's NSE F&O bhavcopy, read index-futures OI by index and
lot (fetch_fii_dii.fo_index_lots — the same parser the daily job uses), then
fetch_fii_dii.apply_lot_factor. Per-day results cache under CACHE so a re-run is offline.
Report: days where the bhavcopy's contract count != the participant file's total (the
unconverted residual), and days with no bhavcopy at all.
Run:  python3 scripts/backfill_fo_lots.py
"""
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_fii_dii as F
from fetch_fo_bhavcopy import url_for

CACHE = os.path.expanduser("~/stocks-wt/fo_lots_cache")
os.makedirs(CACHE, exist_ok=True)
H = {"User-Agent": F.UA, "Referer": "https://www.nseindia.com/"}


def day(ds):
    cp = os.path.join(CACHE, ds + ".json")
    if os.path.exists(cp):
        return ds, json.load(open(cp))
    d = dt.date.fromisoformat(ds)
    for a in range(4):
        try:
            blob = F._get(url_for(d), headers=H, timeout=60, binary=True)
            break
        except Exception as e:
            if getattr(e, "code", None) == 404:
                json.dump({"none": True}, open(cp, "w"))
                return ds, {"none": True}
            time.sleep(2 + 3 * a)
    else:
        return ds, {"err": True}
    L = F.fo_index_lots(d, blob=blob) or {"none": True}
    json.dump(L, open(cp, "w"))
    return ds, L


def main():
    fo = F._load_rows(F.OUT_FO)
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(day, sorted(fo)))
    errs = [d for d, L in res.items() if L.get("err")]
    none = [d for d, L in res.items() if L.get("none")]
    lots = {d: L for d, L in res.items() if "q" in L}
    resid = []
    for d, L in lots.items():
        tot = sum(fo[d]["oi"][p]["futIdx"][0] for p in fo[d]["oi"])
        n = sum(v[1] for v in L["q"].values())
        if abs(n - tot) > 0.5:
            resid.append((d, round(n, 1), tot, round((tot - n) / tot * 100, 3)))
    print("days", len(fo), "with lots", len(lots), "no bhavcopy", none, "fetch errors", errs)
    print("contract-count residual days", len(resid), "max |%|", max((abs(x[3]) for x in resid), default=0))
    for x in sorted(resid, key=lambda x: -abs(x[3]))[:15]:
        print("  ", x)
    if errs:
        print("NOT WRITING — fetch errors; re-run (cached days are skipped)")
        return
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "days": {d: lots[d] for d in sorted(lots)}},
        open(F.OUT_LOTS, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    F.apply_lot_factor(fo, lots)
    rows = [fo[d] for d in sorted(fo)]
    json.dump(
        {"updated": json.load(open(F.OUT_FO))["updated"], "rows": rows},
        open(F.OUT_FO, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print("wrote", F.OUT_LOTS, "and lf on", sum(1 for r in rows if "lf" in r), "rows")
    print("ref lots", lots[max(lots)]["ref"])


if __name__ == "__main__":
    main()
