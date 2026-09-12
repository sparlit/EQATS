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
"""seq-audit resolution probes.

  full KEY [KEY...]        - dump the FULL cached window (every row, no filter)
  wider KEY [KEY...]       - refetch qe+240..qe+540 raw and dump it (appended to cache under key+"#w")
  pdf KEY YYYYMMDD [n]     - download attachment(s) filed on that date (from cached rows) and
                             print the first ~n (default 2) pages of text via pypdf
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _seq_audit_fetch as SA
import backfill_ann_dates_bse as BB
import fetch_insurers as FI

CACHE = SA.CACHE


def dump(rows, title):
    print("=== %s (%d rows) ===" % (title, len(rows)))
    for r in sorted(rows, key=lambda r: r[0]):
        print(
            "  %s | %-14s | %-24s | %s | %s" % (r[0][:16], r[1][:14], r[2][:24], "att" if r[4] else "NOATT", r[3][:130])
        )


def main():
    mode = sys.argv[1]
    cache = BB.jload(CACHE, {})
    if mode == "full":
        for k in sys.argv[2:]:
            c = cache.get(k) or {}
            dump(c.get("rows") or [], "{} window {}..{}".format(k, c.get("lo"), c.get("hi")))
    elif mode == "wider":
        o = FI.bse_session()
        codes = BB.scrip_map()
        today = int(datetime.date.today().strftime("%Y%m%d"))
        for k in sys.argv[2:]:
            sym, qe_s = k.split("|")
            qe = int(qe_s)
            lo = BB.plus(qe, 240)
            hi = min(BB.plus(qe, 540), today)
            rows, pages = SA.fetch_window_raw(o, codes[sym], str(lo), str(hi))
            cache[k + "#w"] = {"code": codes[sym], "lo": lo, "hi": hi, "rows": rows, "pages": pages}
            dump(rows, "%s WIDER %d..%d" % (k, lo, hi))
        BB.jsave(CACHE, cache)
    elif mode == "pdf":
        k, d = sys.argv[2], sys.argv[3]
        npages = int(sys.argv[4]) if len(sys.argv) > 4 else 2
        import io

        from pypdf import PdfReader

        o = FI.bse_session()
        rows = (cache.get(k) or {}).get("rows") or []
        rows += (cache.get(k + "#w") or {}).get("rows") or []
        hit = [r for r in rows if re.sub(r"[^0-9]", "", r[0])[:8] == d and r[4]]
        if not hit:
            print("no attachment rows on", d)
            return
        for r in sorted(hit, key=lambda r: r[0]):
            print(f"### {r[0][:16]} | {r[1]} | {r[2]} | {r[3][:110]}")
            pdf = FI.fetch_pdf(o, r[4])
            if not pdf:
                print(f"   [pdf fetch failed: {r[4]}]")
                continue
            try:
                rd = PdfReader(io.BytesIO(pdf))
                for i, pg in enumerate(rd.pages[:npages]):
                    t = (pg.extract_text() or "").strip()
                    t = re.sub(r"\n{2,}", "\n", t)
                    print("   -- page %d/%d --" % (i + 1, len(rd.pages)))
                    print("   " + t[:2600].replace("\n", "\n   "))
            except Exception as ex:
                print(f"   [pdf parse err: {str(ex)[:80]}]")


if __name__ == "__main__":
    main()
