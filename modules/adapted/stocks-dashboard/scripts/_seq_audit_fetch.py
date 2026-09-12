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
"""§104b seq-entry audit — PHASE 1: fetch RAW BSE announcement windows for every seq-sourced
ann_date_fills.json entry and cache them for offline by-eye adjudication.

RAW = strCat=-1, NO is_result_filing filter (the true results row may carry wording the
result-filter vetoes, e.g. 'Intimation Of Outcome Of Board Meeting' — Tata Motors class),
full NEWS_DT timestamp + CATEGORYNAME + SUBCATNAME kept. Pages until a short page (the
range(1,4) cap in datebound silently truncates chatty large-cap windows — endpoint caps
are silent, so page to exhaustion with a sane ceiling).

Resumable: keys already in the cache are skipped. 8 consecutive empty windows = BSE
rate-limit stub -> abort without recording the burst (162-byte lesson).

Cache: scripts/_seq_audit_rows.json  {key: {"code": scrip, "lo": int, "hi": int,
        "rows": [[NEWS_DT, CATEGORYNAME, SUBCATNAME, NEWSSUB, ATTACHMENTNAME], ...]}}
"""
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backfill_ann_dates_bse as BB
import fetch_insurers as FI

CACHE = os.path.join(HERE, "_seq_audit_rows.json")
SEQ_SRCS = {"bse:seq", "bse:sweep1:seq", "bse:sweep2:seq", "bse:recon:seq"}


def fetch_window_raw(o, code, lo, hi):
    rows_out, total_pages = [], 0
    for pg in range(1, 41):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%s&strSearch=P&strToDate=%s&strType=C" % (pg, lo, code, hi)
        )
        rows = json.loads(FI.bse_get(o, u)).get("Table", [])
        total_pages = pg
        for r in rows:
            rows_out.append(
                [
                    r.get("NEWS_DT") or "",
                    r.get("CATEGORYNAME") or "",
                    r.get("SUBCATNAME") or "",
                    r.get("NEWSSUB") or "",
                    r.get("ATTACHMENTNAME") or "",
                ]
            )
        if len(rows) < 50:
            break
        time.sleep(0.4)
    return rows_out, total_pages


def main():
    ledger = BB.jload(BB.LEDGER, {})
    seq = {k: v for k, v in ledger.items() if isinstance(v, dict) and v.get("src") in SEQ_SRCS}
    cache = BB.jload(CACHE, {})
    codes = BB.scrip_map()
    today = int(datetime.date.today().strftime("%Y%m%d"))

    def gap(k):
        _sym, qe = k.split("|")
        a = seq[k]["ann"]
        return (BB.qe_date(int(a)) - BB.qe_date(int(qe))).days

    todo = sorted((k for k in seq if k not in cache), key=gap)
    print("seq entries: %d, cached: %d, to fetch: %d" % (len(seq), len(cache), len(todo)))

    o = FI.bse_session()
    empty_streak = 0
    streak_keys = []
    done = 0
    for k in todo:
        sym, qe_s = k.split("|")
        qe = int(qe_s)
        code = codes.get(sym)
        if not code:
            cache[k] = {"code": None, "err": "no-scrip"}
            done += 1
            continue
        lo = BB.plus(qe, 1)
        hi = min(BB.plus(qe, 240), today)
        try:
            rows, pages = fetch_window_raw(o, code, str(lo), str(hi))
        except Exception as ex:
            print(f"  {k} fetch err: {str(ex)[:100]}")
            rows, pages = [], 0
        if not rows:
            empty_streak += 1
            streak_keys.append(k)
        else:
            empty_streak = 0
            streak_keys = []
        cache[k] = {"code": code, "lo": lo, "hi": hi, "rows": rows, "pages": pages}
        if empty_streak >= 8:
            for sk in streak_keys:
                cache.pop(sk, None)
            BB.jsave(CACHE, cache)
            print(
                "8 consecutive empty windows — rate-limit suspected; aborting (burst not "
                "recorded). Fetched %d this run." % done
            )
            return
        done += 1
        if done % 10 == 0:
            BB.jsave(CACHE, cache)
            print("… %d/%d fetched (last %s: %d rows, %d pages)" % (done, len(todo), k, len(rows), pages))
        time.sleep(0.6)
    BB.jsave(CACHE, cache)
    print("DONE: %d fetched this run, cache now %d/%d keys" % (done, len(cache), len(seq)))


if __name__ == "__main__":
    main()
