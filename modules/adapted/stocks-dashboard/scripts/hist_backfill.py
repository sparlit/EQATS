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
"""ONE-TIME historical backfill of docs/sf_fundamentals.json: reuse the daily cron's NSE
integrated-filing-results + XBRL parser (build_fundamentals) but sweep a WIDE historical window
(2019-2024) in chunks, so every stock that's currently in the Jan2024->date N500 union gets its
full quarterly history (std+con) wherever NSE has the XBRL. Fill-only; skips already-stored
basis/quarter (so it only fetches XBRLs for genuine gaps). Insurers (IRDAI, no XBRL P&L) and
pre-listing IPO quarters won't be covered here -> handled separately.
Run: python -X utf8 hist_backfill.py
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(HERE, "fundamentals.json")
UNIV = set(json.load(open(os.path.join(HERE, "_full_union_2024.json"))))


def chunks(start, end, days=100):
    d = start
    while d < end:
        e = min(d + datetime.timedelta(days=days), end)
        yield d.strftime("%d-%m-%Y"), e.strftime("%d-%m-%Y")
        d = e


def main():
    data = json.load(open(DOCS))
    jar = B.nse_jar()
    h = {
        "User-Agent": B.UA,
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    }
    start = datetime.date(2019, 4, 1)
    end = datetime.date(2024, 6, 1)
    byq = {}
    for frm, to in chunks(start, end, 100):
        url = (
            "https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly"
            f"&from_date={frm}&to_date={to}"
        )
        try:
            jb = json.loads(B._get(url, headers=h, jar=jar, timeout=45))
            rows = jb if isinstance(jb, list) else jb.get("data", [])
        except Exception as e:
            print(f"window {frm}..{to} FAIL {e}", flush=True)
            continue
        n = 0
        for r in rows:
            sym = r.get("symbol")
            qe = B.iso(r.get("qe_Date"))
            xb = r.get("xbrl", "")
            if sym not in UNIV or not qe or not xb.startswith("http") or int(qe) < 20180101:
                continue
            if "governance" in (r.get("type", "") or "").lower():
                continue
            byq.setdefault((sym, int(qe)), []).append(
                {"ann": B.iso(r.get("broadcast_Date")) or "99999999", "xbrl": xb, "basis": r.get("consolidated", "")}
            )
            n += 1
        print("window %s..%s rows=%d kept=%d uniq=%d" % (frm, to, len(rows), n, len(byq)), flush=True)
        time.sleep(0.5)

    changed = 0
    fetched = 0
    for (sym, qe), filings in byq.items():
        existing = next((x for x in data.get(sym, []) if x[0] == qe), None)
        std = con = None
        annStd = annCon = None
        for f in sorted(filings, key=lambda x: x["ann"]):
            if std is not None and con is not None:
                break
            is_con = "consol" in (f.get("basis") or "").lower()
            if existing and (
                (is_con and len(existing) > 3 and existing[3] is not None) or (not is_con and existing[1] is not None)
            ):
                continue
            try:
                xml = B._get(
                    f["xbrl"], headers={"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}, timeout=30
                )
                fetched += 1
            except Exception:
                continue
            s, c = B.xbrl_profit(xml, basis_hint=f.get("basis"))
            a = None if f["ann"] == "99999999" else int(f["ann"])
            if std is None and s is not None:
                std, annStd = s, a
            if con is None and c is not None:
                con, annCon = c, a
            time.sleep(0.05)
        if std is None and con is None:
            continue
        rec = data.setdefault(sym, [])
        row = next((x for x in rec if x[0] == qe), None)
        if row:
            while len(row) < 5:
                row.append(None)
            if std is not None and row[1] is None:
                row[1], row[2] = std, annStd
                changed += 1
            if con is not None and row[3] is None:
                row[3], row[4] = con, annCon
                changed += 1
        else:
            rec.append([qe, std, annStd, con, annCon])
            rec.sort(key=lambda x: x[0])
            changed += 1
    json.dump(data, open(DOCS, "w"), separators=(",", ":"))
    json.dump(data, open(MIRROR, "w"), separators=(",", ":"))
    print(
        "HIST BACKFILL DONE: fetched %d xbrls, upserted %d fields, %d (sym,qe) seen" % (fetched, changed, len(byq)),
        flush=True,
    )


if __name__ == "__main__":
    main()
