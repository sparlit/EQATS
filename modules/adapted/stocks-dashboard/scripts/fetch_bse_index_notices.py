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
"""Download BSE Index Services' index notices (PDF) that can change BSE SME IPO membership  (runbook §195).

LIST   bseindices.com/AsiaIndexAPI/api/GetNoticesadvancesearch_newcomb/w?FromDate=YYYY-MM-DD&NoticeNo=&Todate=YYYY-MM-DD
       → Table[{notice_no, Subject, dt_tm, FileName (PDF on www.bseindia.com, null for most)}]
PDF    FileName when present, else bseindices.com/AsiaIndexAPI/api/NoticesAsiaDownload/w?NoticeId=<notice_no>   (1,542 notices 2013-01-09 → measured
       2026-09-27; found in bseindices.com's main-*.js)
KEEP   subjects naming the SME IPO index, plus every generic "Reconstitution / Changes / Additions / Deletion /
       Replacement / Review / Inclusion / Exclusion … BSE Indices" notice (monthly drops and migrations ride those).
CACHE  ~/stocks-cache/bse_index_notices/<notice_no>.pdf  (NOT /tmp — scratch caches get deleted) + list.json
PACE   one request at a time, 1.2 s apart, only files not yet cached; a non-PDF body is an error, never "absent".
Run:   python3 scripts/fetch_bse_index_notices.py [--list-only] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import bse_headers  # noqa: F401  §181
import os
import sys
import re
import json
import time
import datetime
import urllib.request

CACHE = os.path.expanduser("~/stocks-cache/bse_index_notices")
LIST = "https://bseindices.com/AsiaIndexAPI/api/GetNoticesadvancesearch_newcomb/w?FromDate=2012-01-01&NoticeNo=&Todate=%s"
HDR = {
    "User-Agent": bse_headers.UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindices.com/",
}
KEEP = re.compile(
    r"(?i)sme|reconstitut|changes? (?:to|in)|addition|deletion|replacement|review|inclusion|exclusion"
)


EMPTY = os.path.join(
    CACHE, "_empty.json"
)  # notices the download route answered with a 0-byte body (not "absent")


def get(url, accept_pdf=False):
    h = dict(HDR)
    if "bseindia.com" in url:
        h["Referer"] = "https://www.bseindia.com/"
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=120) as r:
                b = r.read()
            if accept_pdf and len(b) == 0:
                return b  # measured: some pre-2013 notices are served as an empty 200
            if accept_pdf and not b.startswith(b"%PDF"):
                raise RuntimeError("not a PDF (%d bytes, starts %r)" % (len(b), b[:40]))
            return b
        except Exception as e:
            last = e
            print("  retry %d %s: %r" % (i + 1, url[-40:], e), flush=True)
            time.sleep(6 * (i + 1))
    raise RuntimeError(f"{url}: {last!r}")


def main():
    os.makedirs(CACHE, exist_ok=True)
    rows = json.loads(get(LIST % datetime.date.today().isoformat())).get("Table") or []
    if len(rows) < 1000:
        raise SystemExit("notice list has %d rows — refusing" % len(rows))
    # the index launched 14-Dec-2012 (notice 20121214-11): nothing earlier can change its membership
    lo = sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else "2012-12-01"
    hi = sys.argv[sys.argv.index("--to") + 1] if "--to" in sys.argv else "9999"
    keep = [
        r
        for r in rows
        if KEEP.search(r.get("Subject") or "")
        and lo <= (r.get("dt_tm") or "") >= "2012-12-01"
        and (r.get("dt_tm") or "")[:10] <= hi
    ]
    with open(os.path.join(CACHE, "list.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"fetched": datetime.datetime.now().isoformat(timespec="seconds"), "all": rows},
            f,
            ensure_ascii=False,
        )
    print("notices: %d listed, %d kept" % (len(rows), len(keep)))
    if "--list-only" in sys.argv:
        return
    empty = set(json.load(open(EMPTY))) if os.path.exists(EMPTY) else set()
    got = skip = 0
    for r in sorted(keep, key=lambda x: x["dt_tm"]):
        no = r["notice_no"]
        p = os.path.join(CACHE, no + ".pdf")
        if (os.path.exists(p) and os.path.getsize(p) > 1000) or no in empty:
            skip += 1
            continue
        # FileName is null on 1,466 of 1,582 rows (notice_flag 0); the site's own download route serves every notice
        url = r.get("FileName") or (
            "https://bseindices.com/AsiaIndexAPI/api/NoticesAsiaDownload/w?NoticeId=" + no
        )
        b = get(url, accept_pdf=True)
        if not b:
            empty.add(no)
            with open(EMPTY, "w") as f:
                json.dump(sorted(empty), f)
            time.sleep(1.2)
            continue
        with open(p + ".tmp", "wb") as f:
            f.write(b)
        os.replace(p + ".tmp", p)
        got += 1
        if got % 50 == 0:
            print("  %d downloaded (last %s %s)" % (got, no, r["dt_tm"][:10]), flush=True)
        time.sleep(1.2)
    print("done: %d downloaded, %d already cached, %d served empty" % (got, skip, len(empty)))


if __name__ == "__main__":
    main()
