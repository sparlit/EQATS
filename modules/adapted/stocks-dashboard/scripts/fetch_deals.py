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
"""Fetch NSE BULK + BLOCK deals (the "smart money" tape) into a rolling window:
docs/deals.json — read by the Bulk & Block Deals page + the Discovery bucket.

SOURCES (each non-fatal; every one carries only the LATEST trading day, so the
window builds up day by day and self-heals via merge):
  1. https://nsearchives.nseindia.com/content/equities/bulk.csv   (plain UA — CI-proven host)
  2. https://nsearchives.nseindia.com/content/equities/block.csv  ("NO RECORDS" rows on no-deal days)
  3. https://www.nseindia.com/api/snapshot-capital-market-largedeal  (urllib + cookie warmup —
     same CI-proven session as the announcements cron; its BLOCK section can carry an OLDER
     date than bulk when today had no block deals — merging by date handles that)
  4. OPPORTUNISTIC top-up: /api/historical/bulk-deals + block-deals via curl_cffi *if importable*.
     As of 2026-07-16 this endpoint 503s even with TLS impersonation (Akamai) — the attempt is
     cheap and non-fatal; if NSE ever unblocks it, window holes self-heal automatically.

- Self-healing: merges with the existing file (a failed day keeps old rows), trims to WINDOW_DAYS.
- Never-shrink guard: refuses to write if the merge lost >40% of the existing rows.
- Exit 1 only when EVERY source failed (visible red run; previous file stays live).

Output schema (compact arrays):
  {"updated","from","to",
   "rows":[[date "YYYY-MM-DD", kind "B"(bulk)|"K"(block), symbol, company, client,
            side "B"|"S", qty, price], ...]}      value ₹cr = qty*price/1e7, computed client-side
Dedup key = (date,kind,symbol,CLIENT,side,qty,price) — name excluded (CSV & API spell it
differently); CSV is parsed first so its fuller company name wins.

Run: python -X utf8 scripts/fetch_deals.py
"""
import csv
import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "deals.json")
WINDOW_DAYS = 92
MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def iso_date(s):
    """'15-JUL-2026' / '15-Jul-2026' / '2026-07-15' -> 'YYYY-MM-DD' (None if unparseable)."""
    s = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})[A-Za-z]*-(\d{4})$", s)
    if not m:
        return None
    mo = MON.get(m.group(2).lower())
    return "%s-%02d-%02d" % (m.group(3), mo, int(m.group(1))) if mo else None


def to_num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


# per-field candidate keys, checked in order, on a lowercased-key copy of the record
FIELD_KEYS = {
    "date": ["bd_dt_date", "date", "deal_date"],
    "sym": ["bd_symbol", "symbol"],
    "name": ["bd_scrip_name", "security name", "security_name", "name"],
    "client": ["bd_client_name", "client name", "clientname", "client_name"],
    "side": ["bd_buy_sell", "buy/sell", "buysell", "buy_sell"],
    "qty": ["bd_qty_trd", "quantity traded", "qty", "quantity_traded"],
    "price": ["bd_tp_watp", "trade price / wght. avg. price", "watp", "price"],
}


def norm_rec(rec, kind):
    low = {str(k).strip().lower(): v for k, v in rec.items() if k}

    def g(f):
        for k in FIELD_KEYS[f]:
            if k in low and low[k] not in (None, ""):
                return low[k]
        return None

    dt = iso_date(g("date"))
    sym = str(g("sym") or "").strip().upper()
    name = " ".join(str(g("name") or "").split())
    client = " ".join(str(g("client") or "").split())
    side = str(g("side") or "").strip().upper()[:1]  # B / S
    qty, px = to_num(g("qty")), to_num(g("price"))
    if not (dt and sym and client and side in ("B", "S") and qty and qty > 0 and px and px > 0):
        return None
    return [dt, kind, sym, name, client, side, int(qty), round(px, 2)]


def key_of(r):
    return "|".join(str(x) for x in (r[0], r[1], r[2], r[4].upper(), r[5], r[6], r[7]))


def add(rows, recs, kind, label):
    n = 0
    for rec in recs:
        r = norm_rec(rec, kind) if isinstance(rec, dict) else None
        if r and rows.setdefault(key_of(r), r) is r:
            n += 1
    print("  %s: +%d rows" % (label, n), flush=True)
    return n


def main():
    today = datetime.date.today()
    lo = (today - datetime.timedelta(days=WINDOW_DAYS - 1)).isoformat()
    jar = B.nse_jar()
    rows, ok_sources = {}, 0

    # --- 1+2: archives CSVs (latest trading day; block.csv says NO RECORDS on no-deal days) ---
    for kind, fn in (("B", "bulk.csv"), ("K", "block.csv")):
        try:
            t = B._get(
                "https://nsearchives.nseindia.com/content/equities/" + fn, headers={"User-Agent": B.UA}, timeout=60
            )
            recs = list(csv.DictReader(io.StringIO(t)))
            add(rows, recs, kind, "archives " + fn)
            ok_sources += 1
        except Exception as ex:
            print(f"  archives {fn} FAILED: {ex}", flush=True)

    # --- 3: snapshot API (same day as CSVs; block section may carry the last block-deal day) ---
    try:
        hdr = {
            "User-Agent": B.UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/market-data/large-deals",
        }
        j = json.loads(
            B._get("https://www.nseindia.com/api/snapshot-capital-market-largedeal", headers=hdr, jar=jar, timeout=60)
        )
        add(rows, j.get("BULK_DEALS_DATA") or [], "B", "snapshot bulk")
        add(rows, j.get("BLOCK_DEALS_DATA") or [], "K", "snapshot block")
        ok_sources += 1
    except Exception as ex:
        print(f"  snapshot API FAILED: {ex}", flush=True)

    # --- 4: opportunistic historical top-up (blocked 503 as of 2026-07-16; free to try) ---
    try:
        from curl_cffi import requests as creq

        s = creq.Session(impersonate="chrome")
        s.get("https://www.nseindia.com/", timeout=30)
        for kind, ep in (("B", "bulk-deals"), ("K", "block-deals")):
            r = s.get(
                "https://www.nseindia.com/api/historical/{}?from={}&to={}".format(
                    ep,
                    (today - datetime.timedelta(days=WINDOW_DAYS - 1)).strftime("%d-%m-%Y"),
                    today.strftime("%d-%m-%Y"),
                ),
                headers={"Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"},
                timeout=45,
            )
            if r.status_code == 200:
                add(rows, (r.json().get("data") or []), kind, "historical " + ep)
                ok_sources += 1
            else:
                print("  historical %s: HTTP %d (expected while Akamai-blocked)" % (ep, r.status_code), flush=True)
    except ImportError:
        pass
    except Exception as ex:
        print(f"  historical top-up skipped: {ex}", flush=True)

    fresh = len(rows)
    # --- self-heal: keep existing rows inside the window that this run didn't see ---
    old_n = 0
    try:
        old = json.load(open(OUT, encoding="utf-8"))
        old_rows = [r for r in old.get("rows", []) if r[0] >= lo]
        old_n = len(old_rows)
        for r in old_rows:
            rows.setdefault(key_of(r), r)
    except Exception:
        pass

    if ok_sources == 0 and old_n == 0:
        print("ALL sources failed and no previous file — nothing to write", flush=True)
        sys.exit(1)
    if ok_sources == 0:
        print("ALL sources failed — keeping the previous file untouched (visible red run)", flush=True)
        sys.exit(1)
    if old_n and len(rows) < 0.6 * old_n:
        print("REFUSING to write: merged %d rows < 60%% of previous %d" % (len(rows), old_n), flush=True)
        sys.exit(1)

    allr = sorted(rows.values(), key=lambda r: (r[0], r[2], r[1], r[4]), reverse=True)
    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M"), "from": lo, "to": today.isoformat(), "rows": allr}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    days = sorted({r[0] for r in allr})
    print(
        "Wrote %s: %d rows (%d fresh) over %d deal-days %s..%s (%.0f KB)"
        % (
            OUT,
            len(allr),
            fresh,
            len(days),
            days[0] if days else "-",
            days[-1] if days else "-",
            os.path.getsize(OUT) / 1024.0,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
