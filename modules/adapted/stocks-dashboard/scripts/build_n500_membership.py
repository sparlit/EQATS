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
Rebuild point-in-time Nifty 500 membership from ACCURATE archived constituent lists
(NSE archive + niftyindices.com, via the Internet Archive), aligned to NSE's
semi-annual reconstitution calendar (effective ~Apr 1 and ~Oct 1).

Fixes the bug where the old scrapbook (indices_history.json) dropped/added stocks
on wrong dates (e.g. SCI vanished in Feb-2023 though NSE only reshuffles end-Mar).

Each captured list is valid for the reshuffle window it belongs to; the backtest's
membersAsOf() uses lastSnap (effectiveDate <= date), so we stamp each list with the
date it BECAME effective. Pre-2018 (before our earliest accurate capture) keeps the
old scrapbook so deep-history backtests still have a Nifty 500 universe.

Updates: scripts/indices_history.json  AND  docs/stock_data.bin (indicesHistory).
Run: python -X utf8 build_n500_membership.py
"""
import csv
import gzip
import io
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# (wayback timestamp, source-url) for every unique-content capture we found
NSE = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NI = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
CAPTURES = [
    ("20181004105632", NI),
    ("20190201175107", NI),
    ("20210204102409", NI),
    ("20220504103923", NSE),
    ("20221009160959", NSE),
    ("20230404164710", NSE),
    ("20240207233933", NI),
    ("20240226224931", NSE),
    ("20250616113621", NI),
    ("20250815235304", NI),
    ("20250824025802", NI),
    ("20260107050129", NI),
    ("20260502114023", NI),
]


def wb_get(ts, url, tries=6):
    u = f"http://web.archive.org/web/{ts}id_/{url}"
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
        except Exception as e:
            last = e
            time.sleep(4)
    raise last


def parse(raw):
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    txt = raw.decode("utf-8", "ignore")
    rows = list(csv.reader(txt.splitlines()))
    if not rows:
        return []
    hdr = [h.strip() for h in rows[0]]
    si = hdr.index("Symbol") if "Symbol" in hdr else 2
    return sorted({r[si].strip() for r in rows[1:] if len(r) > si and r[si].strip()})


def eff_date(ts):
    """Map a capture (YYYYMM...) to the reshuffle effective date it represents."""
    y, m = int(ts[:4]), int(ts[4:6])
    if 4 <= m <= 9:
        return f"{y}-04-01"
    if m >= 10:
        return f"{y}-10-01"
    return f"{y - 1}-10-01"  # Jan-Mar -> previous Oct reshuffle


def main():
    # 1) fetch + validate every capture, keep best (most symbols) per reshuffle window
    by_eff = {}
    for ts, url in CAPTURES:
        try:
            syms = parse(wb_get(ts, url))
        except Exception as e:
            print(f"  {ts[:8]}  FETCH-FAIL {e}")
            continue
        ok = len(syms) >= 450 and "RELIANCE" in syms and "TCS" in syms
        if not ok:
            print(f"  {ts[:8]}  REJECT (count={len(syms)}, RELIANCE={'RELIANCE' in syms})")
            continue
        eff = eff_date(ts)
        if eff not in by_eff or len(syms) > len(by_eff[eff][1]):
            by_eff[eff] = (ts[:8], syms)
        print(f"  {ts[:8]}  OK count={len(syms)}  -> window eff={eff}  SCI={'SCI' in syms}")
    accurate = [
        {"effectiveDate": eff, "symbols": syms, "src": f"archive:{cap}"} for eff, (cap, syms) in sorted(by_eff.items())
    ]
    print(f"\nAccurate reshuffle windows: {[a['effectiveDate'] for a in accurate]}")
    if not accurate:
        print("No accurate snapshots — aborting.")
        return
    earliest = accurate[0]["effectiveDate"]

    # 2) keep OLD scrapbook snapshots only for dates strictly before our accurate data
    hist_path = os.path.join(HERE, "indices_history.json")
    H = json.load(open(hist_path, encoding="utf-8"))
    old = H.get("Nifty 500", [])
    kept_old = [s for s in old if s["effectiveDate"] < earliest]
    new_n500 = sorted(
        kept_old + [{"effectiveDate": a["effectiveDate"], "symbols": a["symbols"]} for a in accurate],
        key=lambda s: s["effectiveDate"],
    )
    print(
        f"Old scrapbook snapshots kept (pre-{earliest}): {len(kept_old)} | accurate added: {len(accurate)} | total: {len(new_n500)}"
    )

    # 3) write indices_history.json
    H["Nifty 500"] = new_n500
    json.dump(H, open(hist_path, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"Updated {hist_path}")

    # 4) splice into docs/stock_data.bin (the file the backtest actually loads)
    binp = os.path.join(ROOT, "docs", "stock_data.bin")
    D = json.loads(gzip.decompress(open(binp, "rb").read()))
    D.setdefault("indicesHistory", {})["Nifty 500"] = new_n500
    open(binp, "wb").write(gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6))
    print(f"Updated {binp}")

    # 5) quick self-check: SCI on the 2023-03-31 rebalance
    def members_asof(snaps, d):
        best = None
        for s in snaps:
            if s["effectiveDate"] <= d and (not best or s["effectiveDate"] > best["effectiveDate"]):
                best = s
        return set(best["symbols"]) if best else set()

    m = members_asof(new_n500, "2023-03-31")
    print(f"\nSELF-CHECK membersAsOf('2023-03-31'): size={len(m)}  SCI in it? {'SCI' in m}")


if __name__ == "__main__":
    main()
