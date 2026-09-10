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
Top up sf_fundamentals.json with RECENT quarters from NSE's Integrated Filing endpoint.

WHY: NSE moved quarterly financial results to the "Integrated Filing" system in early 2025.
The old `corporates-financial-results?period=Quarterly` endpoint (used by build_fundamentals.py)
now freezes at the Dec-2024 quarter for every symbol — so all earnings data went stale there.
This script fetches the missing quarters from `integrated-filing-results` and merges them in,
without touching the historical (<= Dec-2024) data the old endpoint already provided.

The integrated INDAS iXBRL uses the in-capmkt: namespace but the SAME context convention:
  OneD = the current 3-month quarter, FourD = year-to-date. Basis (Standalone/Consolidated)
  comes from the filing's `consolidated` field (each basis is a separate filing).

Run:  python -X utf8 topup_fundamentals.py            # top up every symbol already in the file
      python -X utf8 topup_fundamentals.py SYM1 SYM2  # just these (test)
Cache: reuses build_fundamentals' _xbrl_cache (gitignored). Resumable: re-run is mostly cache hits.
"""
import concurrent.futures
import json
import os
import re
import threading
import time
import urllib.parse

import build_fundamentals as bf

DOCS = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_fundamentals.json")
OUT = bf.OUT


def integrated_profit(xml):
    """Net profit (₹ crore) for the CURRENT quarter from an Integrated-Filing INDAS iXBRL.
    OneD = current 3-month quarter (any namespace). Falls back to FourD only if OneD is absent."""
    # Banks/NBFCs use ProfitLossForThePeriod (with "The"); everyone else ProfitLossForPeriod.
    for ctx in ("OneD", "FourD"):
        m = re.search(rf'ProfitLossFor(?:The)?Period contextRef="{ctx}"[^>]*>([-0-9.eE+]+)<', xml)
        if m:
            try:
                return round(float(m.group(1)) / 1e7, 2)
            except Exception:
                return None
        if ctx == "OneD" and m is None:
            continue
    return None


def fetch_integrated(sym, jar):
    url = f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={urllib.parse.quote(sym)}&period=Quarterly"
    try:
        rows = json.loads(
            bf._get(
                url,
                headers={"User-Agent": bf.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"},
                jar=jar,
                timeout=30,
            )
        ).get("data", [])
    except Exception:
        return None  # signal "retry with fresh cookies"
    byq = {}  # qEnd -> {std:(np,ann), con:(np,ann)}
    # NSE returns duplicate rows per (qe,basis) — one dated, one broadcast_Date=None. Take the
    # DATED one first so we don't store a null announcement date (engine skips date-less quarters).
    rows.sort(key=lambda r: 0 if r.get("broadcast_Date") else 1)
    for r in rows:
        xb = r.get("xbrl") or ""
        # Financials only (skip GOVERNANCE). Schema varies: INTEGRATED_FILING_INDAS (most cos),
        # _BANKING (banks), _NBFC_INDAS (NBFCs) — all carry net profit, so filter by filing type.
        if r.get("type") != "Integrated Filing- Financials" or not xb:
            continue
        qe = bf.iso(r.get("qe_Date"))
        ann = bf.iso(r.get("broadcast_Date"))
        if not qe:
            continue
        key = "con" if "consol" in (r.get("consolidated") or "").lower() else "std"
        d = byq.setdefault(qe, {})
        if key in d:
            continue
        cf = os.path.join(bf.CACHE, re.sub(r"[^A-Za-z0-9]", "_", xb.rsplit("/", 1)[-1]))
        try:
            if os.path.exists(cf) and os.path.getsize(cf) > 500:
                xml = open(cf, encoding="utf-8").read()
            else:
                xml = bf._get(xb, headers={"User-Agent": bf.UA, "Referer": "https://www.nseindia.com/"}, timeout=45)
                open(cf, "w", encoding="utf-8").write(xml)
                time.sleep(0.1)
        except Exception:
            continue
        np = integrated_profit(xml)
        if np is None:
            continue
        d[key] = (np, int(ann) if ann else None)
    return byq


def merge(existing, byq):
    """Merge integrated recent quarters into the existing [qEnd, npStd, annStd, npCon, annCon] list."""
    m = {row[0]: list(row) for row in (existing or [])}
    for qe, d in byq.items():
        qi = int(qe)
        row = m.get(qi, [qi, None, None, None, None])
        if "std" in d:
            row[1], row[2] = d["std"]
        if "con" in d:
            row[3], row[4] = d["con"]
        m[qi] = row
    return [m[k] for k in sorted(m)]


def main():
    import sys

    data = json.load(open(DOCS))
    a = sys.argv[1:]
    if a and a[0].startswith("@"):  # @file → one symbol per line (targeted re-run)
        syms = [l.strip() for l in open(a[0][1:], encoding="utf-8") if l.strip()]
    else:
        syms = a or list(data.keys())
    print("topping up %d symbols from Integrated-Filing endpoint" % len(syms))
    _tl = threading.local()

    def jar():
        if not getattr(_tl, "jar", None):
            _tl.jar = bf.nse_jar()
        return _tl.jar

    def do(sym):
        byq = fetch_integrated(sym, jar())
        if byq is None:  # cookies likely stale — re-warm once
            _tl.jar = bf.nse_jar()
            byq = fetch_integrated(sym, _tl.jar)
        return sym, byq

    lock = threading.Lock()
    done = 0
    updated = 0

    def flush():
        json.dump(data, open(DOCS, "w"), separators=(",", ":"))
        json.dump(data, open(OUT, "w"), separators=(",", ":"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for sym, byq in ex.map(do, syms):
            done += 1
            with lock:
                if byq:
                    before = max((q[0] for q in data.get(sym, [])), default=0)
                    data[sym] = merge(data.get(sym), byq)
                    after = max(q[0] for q in data[sym])
                    if after > before:
                        updated += 1
                        if updated % 25 == 0 or len(syms) < 20:
                            print(
                                "  [%d/%d] %s: latest %d -> %d  (updated %d)"
                                % (done, len(syms), sym, before, after, updated)
                            )
                if done % 100 == 0 or done == len(syms):
                    flush()
                    print("  ...progress %d/%d, %d updated" % (done, len(syms), updated))
    flush()
    print("DONE. %d of %d symbols got newer quarters." % (updated, len(syms)))


if __name__ == "__main__":
    main()
