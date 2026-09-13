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
"""Backfill missing announcement dates in sf_fundamentals.json.

NSE's integrated-filing endpoint returns duplicate rows per (quarter, basis): one with the
real broadcast_Date and one with broadcast_Date=None. The build sometimes kept the null one,
so the net profit is present but annStd/annCon is None -> the backtest engine SKIPS that
quarter (point-in-time: no date = can't prove it was public). This re-fetches the real
earliest broadcast date per (qe, basis) and fills the nulls. NSE-only (won't touch BSE run).
"""
import json
import os
import time
import urllib.parse

import build_fundamentals as B

DOCS = os.path.join(os.path.dirname(B.HERE), "docs", "sf_fundamentals.json")
OUT = B.OUT
H = {"User-Agent": B.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}


def best_dates(sym, jar):
    """{(qeInt, 'std'|'con'): earliestAnnInt} from integrated filings (prefer real broadcast dates)."""
    url = f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={urllib.parse.quote(sym)}&period=Quarterly"
    try:
        rows = json.loads(B._get(url, headers=H, jar=jar, timeout=30)).get("data", [])
    except Exception:
        return None
    out = {}
    for r in rows:
        if r.get("type") != "Integrated Filing- Financials":
            continue
        qe = B.iso(r.get("qe_Date"))
        bc = B.iso(r.get("broadcast_Date"))
        if not qe or not bc:
            continue
        basis = "con" if "consol" in (r.get("consolidated") or "").lower() else "std"
        k = (int(qe), basis)
        if k not in out or int(bc) < out[k]:  # earliest broadcast = first time it was public
            out[k] = int(bc)
    return out


def main():
    data = json.load(open(DOCS))
    targets = sorted(
        {
            s
            for s, rows in data.items()
            for r in rows
            for npi, ai in ((1, 2), (3, 4))
            if r[npi] is not None and r[ai] is None
        }
    )
    print("symbols with a missing announcement date:", len(targets))
    jar = B.nse_jar()
    filled = 0
    touched = 0
    for i, sym in enumerate(targets, 1):
        bd = best_dates(sym, jar)
        if bd is None:
            jar = B.nse_jar()
            bd = best_dates(sym, jar)  # re-warm cookies once
        if not bd:
            continue
        ch = False
        for r in data[sym]:
            qe = r[0]
            if r[1] is not None and r[2] is None and (qe, "std") in bd:
                r[2] = bd[(qe, "std")]
                filled += 1
                ch = True
            if r[3] is not None and r[4] is None and (qe, "con") in bd:
                r[4] = bd[(qe, "con")]
                filled += 1
                ch = True
        if ch:
            touched += 1
        if i % 50 == 0:
            json.dump(data, open(DOCS, "w"), separators=(",", ":"))
            json.dump(data, open(OUT, "w"), separators=(",", ":"))
            print("  ...%d/%d symbols, %d dates filled" % (i, len(targets), filled))
        time.sleep(0.15)
    json.dump(data, open(DOCS, "w"), separators=(",", ":"))
    json.dump(data, open(OUT, "w"), separators=(",", ":"))
    print("DONE. filled %d missing dates across %d symbols." % (filled, touched))


if __name__ == "__main__":
    main()
