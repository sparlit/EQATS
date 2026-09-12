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
"""Cash-separation sweep (PLAN H.1, user-approved policy): find LARGE dividends whose record
date fell INSIDE a holding window of either DII trade log, so the price-return backtest booked
shareholder cash as a loss (the HGS ₹150 class).

Method, per trade window (548 trades, 2004-2026):
  1. BSE announcements for the symbol across [entry, exit + 5d].
  2. Rows mentioning 'dividend' with an extractable ₹-per-share amount and record-date language.
  3. Candidate when amount >= 2% of the trade's entry price (the demerger ledger's own
     materiality floor). Everything below 2% is ordinary-dividend noise every price-return
     backtest ignores (quantmac's replication included).
Output: scripts/_staleness_fix/dividend_sweep_results.json — candidates only, NO ledger writes
(each needs its ex-day bhavcopy check before a factor is written, same as HGS).
"""
import csv
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib

import fetch_and_match as m

OUT = os.path.join(HERE, "dividend_sweep_results.json")
LOG = os.path.join(HERE, "dividend_sweep.log")

AMT = re.compile(
    r"(?:dividend|div\.?)\s*(?:of|@|:)?\s*(?:rs\.?|rupees|inr|₹)\s*([0-9]+(?:\.[0-9]+)?)"
    r"|(?:rs\.?|₹)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/-|per\s+(?:equity\s+)?share)",
    re.IGNORECASE,
)
DIVY = re.compile(r"dividend", re.IGNORECASE)


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")


def ymd(s):
    return int(s.replace("-", ""))


def main():
    by_id = json.load(open(os.path.join(HERE, "..", "bse_scrips.json")))["by_id"]
    master_by = {}
    for r in json.load(open(os.path.join(HERE, "..", "_bse_master_all.json"))):
        sid, cd = r.get("scrip_id"), r.get("SCRIP_CD")
        if sid and cd and sid not in master_by:
            with contextlib.suppress(TypeError, ValueError):
                master_by[sid] = int(cd)
    trades = []
    for path in [
        "/Users/dhruvan/Downloads/trade-log_diiPct_2004-03-31_2009-01-01.csv",
        "/Users/dhruvan/Downloads/trade-log_diiPct_2009-01-01_2026-08-17.csv",
    ]:
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            try:
                e0, e1 = ymd(r["Entry Date"]), ymd(r["Exit Date"])
                px = float(r["Entry Price"])
            except Exception:
                continue
            if e0 >= e1:
                continue
            trades.append((r["Stock"].strip(), e0, e1, px, r.get("Return %", "")))
    log(f"START {len(trades)} trade windows")

    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    done = 0
    for sym, e0, e1, px, _ret in trades:
        key = f"{sym}|{e0}|{e1}"
        if key in results:
            continue
        sc = by_id.get(sym) or master_by.get(sym)
        entry = {"scripcode": sc, "candidates": [], "error": None}
        if not sc:
            entry["error"] = "no-scripcode"
        else:
            d1 = str(e0)
            d2 = (datetime.date(e1 // 10000, e1 // 100 % 100, e1 % 100) + datetime.timedelta(days=5)).strftime("%Y%m%d")
            try:
                u = (
                    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
                    f"pageno=1&strCat=-1&strPrevDate={d1}&strToDate={d2}"
                    f"&strScrip={sc}&strSearch=P&strType=C&subcategory=-1"
                )
                j = json.loads(m.get(u))
                for row in j.get("Table") or []:
                    text = f"{row.get('NEWSSUB') or ''} {row.get('HEADLINE') or ''}"
                    if not DIVY.search(text):
                        continue
                    amt = None
                    for g in AMT.finditer(text):
                        v = float(g.group(1) or g.group(2))
                        if amt is None or v > amt:
                            amt = v
                    if amt and px > 0 and amt / px >= 0.02:
                        entry["candidates"].append(
                            {
                                "news_dt": row.get("NEWS_DT"),
                                "amt": amt,
                                "pct_of_entry": round(100 * amt / px, 2),
                                "sub": (row.get("NEWSSUB") or "")[:120],
                            }
                        )
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
                log(f"  FAILED {key}: {entry['error']}")
        if entry["candidates"]:
            log(
                f"  CANDIDATE {sym} {e0}->{e1} px={px}: "
                + "; ".join(f"Rs{c['amt']} ({c['pct_of_entry']}%)" for c in entry["candidates"])
            )
        results[key] = entry
        done += 1
        if done % 20 == 0:
            json.dump(results, open(OUT, "w"))
            log(f"CHECKPOINT {done}")
        time.sleep(0.4)
    json.dump(results, open(OUT, "w"))
    ncand = sum(1 for v in results.values() if v.get("candidates"))
    log(f"COMPLETE windows={len(results)} with-candidates={ncand}")


if __name__ == "__main__":
    main()
