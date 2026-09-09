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
"""
Backfill INTERNAL quarter gaps in docs/sf_fundamentals.json.

WHY: the historical build (old corporates-financial-results endpoint) parsed bank/NBFC
net profit with a regex that missed the ProfitLossForThePeriod tag, so many financials
have holes in their 2018-2024 history (KARURVYSYA -11 quarters, CUB -8, INDUSINDBK -8...).
The parser is now fixed (build_fundamentals.xbrl_profit handles ...ForThePeriod), and the
old endpoint still serves those quarters, so we re-fetch and FILL the gaps.

Targets only LIVE symbols (delisted names aren't served by NSE) that actually have a gap.
Old endpoint only (pre-2025) — the 2025+ quarters are already handled by topup_fundamentals.
Fill-only & point-in-time: never overwrites an existing value, only adds missing
quarters / fills null std|con. Resumable: re-run is mostly XBRL cache hits.

Run:  python -X utf8 backfill_gaps.py
"""
import concurrent.futures
import gzip
import json
import os
import re
import threading
import time
import urllib.parse

import build_fundamentals as bf

DOCS = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_fundamentals.json")
OUT = bf.OUT
BIN = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_stock_data.bin")


def nxt(q):
    y, m = q // 10000, (q // 100) % 100
    m += 3
    if m > 12:
        m -= 12
        y += 1
    return y * 10000 + m * 100 + (31 if m in (3, 12) else 30)


def gap_count(arr):
    qs = sorted({r[0] for r in arr if (r[1] is not None or r[3] is not None)})
    if len(qs) < 2:
        return 0
    exp = set()
    c = qs[0]
    while c <= qs[-1]:
        exp.add(c)
        c = nxt(c)
    return len(exp - set(qs))


def fetch_old(sym, jar):
    """Old corporates-financial-results endpoint only (covers ~2018..2024), re-parsed
    with the corrected xbrl_profit. Returns [[qe,npStd,annStd,npCon,annCon],...] or None."""
    h = {
        "User-Agent": bf.UA,
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    }
    enc = urllib.parse.quote(sym)
    try:
        rows = json.loads(
            bf._get(
                f"https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={enc}&period=Quarterly",
                headers=h,
                jar=jar,
                timeout=30,
            )
        )
    except Exception:
        return None
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    byq = {}
    for r in rows:
        qe = bf.iso(r.get("toDate"))
        xb = r.get("xbrl", "")
        if not qe or not xb.startswith("http"):
            continue
        byq.setdefault(qe, []).append(
            {"ann": bf.iso(r.get("broadCastDate")) or "99999999", "xbrl": xb, "basis": r.get("consolidated", "")}
        )
    out = []
    for qe in sorted(byq):
        if int(qe) < bf.MIN_QE:
            continue
        std = con = None
        annStd = annCon = None
        for f in sorted(byq[qe], key=lambda x: x["ann"]):
            if std is not None and con is not None:
                break
            cf = os.path.join(bf.CACHE, re.sub(r"[^A-Za-z0-9]", "_", f["xbrl"].rsplit("/", 1)[-1]))
            try:
                if os.path.exists(cf) and os.path.getsize(cf) > 500:
                    xml = open(cf, encoding="utf-8").read()
                else:
                    xml = bf._get(
                        f["xbrl"], headers={"User-Agent": bf.UA, "Referer": "https://www.nseindia.com/"}, timeout=30
                    )
                    open(cf, "w", encoding="utf-8").write(xml)
                    time.sleep(0.15)
            except Exception:
                continue
            s, c = bf.xbrl_profit(xml, basis_hint=f.get("basis"))
            a = None if f["ann"] == "99999999" else int(f["ann"])
            if std is None and s is not None:
                std, annStd = s, a
            if con is None and c is not None:
                con, annCon = c, a
        if std is None and con is None:
            continue
        out.append([int(qe), std, annStd, con, annCon])
    return out


def merge_fill(existing, fetched):
    """Add missing quarters and fill null std|con; never overwrite an existing value."""
    m = {r[0]: list(r) for r in existing}
    for r in fetched:
        row = m.get(r[0])
        if row is None:
            m[r[0]] = list(r)
        else:
            if row[1] is None and r[1] is not None:
                row[1], row[2] = r[1], r[2]
            if row[3] is None and r[3] is not None:
                row[3], row[4] = r[3], r[4]
    return [m[k] for k in sorted(m)]


def main():
    data = json.load(open(DOCS))
    D = json.loads(gzip.decompress(open(BIN, "rb").read()))
    meta = D.get("meta", {})

    def live(s):
        return meta.get(s, {}).get("alive") is not False

    targets = sorted(
        [s for s, a in data.items() if a and gap_count(a) > 0 and live(s)], key=lambda s: -gap_count(data[s])
    )
    print(
        "gapped live symbols to backfill: %d (total missing quarters: %d)"
        % (len(targets), sum(gap_count(data[s]) for s in targets))
    )

    _tl = threading.local()

    def jar():
        if not getattr(_tl, "jar", None):
            _tl.jar = bf.nse_jar()
        return _tl.jar

    def do(sym):
        out = fetch_old(sym, jar())
        if out is None:
            _tl.jar = bf.nse_jar()
            out = fetch_old(sym, _tl.jar)
        return sym, out

    lock = threading.Lock()
    done = filled = quarters = 0

    def flush():
        json.dump(data, open(DOCS, "w"), separators=(",", ":"))
        json.dump(data, open(OUT, "w"), separators=(",", ":"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for sym, out in ex.map(do, targets):
            done += 1
            with lock:
                if out:
                    before = gap_count(data.get(sym, []))
                    data[sym] = merge_fill(data.get(sym, []), out)
                    after = gap_count(data[sym])
                    if after < before:
                        filled += 1
                        quarters += before - after
                if done % 50 == 0 or done == len(targets):
                    flush()
                    print(
                        "  ...%d/%d  symbols improved=%d  quarters filled=%d" % (done, len(targets), filled, quarters)
                    )
    flush()
    print("DONE. filled %d quarters across %d symbols." % (quarters, filled))


if __name__ == "__main__":
    main()
