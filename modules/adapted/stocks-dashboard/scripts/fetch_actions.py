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
"""Fetch the NSE CORPORATE-ACTIONS calendar (ex-dates for dividends, bonuses, splits,
rights, buybacks) -> docs/actions.json for the Ex-Dates Calendar page.

SOURCE (urllib + cookie warmup — the announcements cron's CI-proven session):
  /api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
  fields: symbol, comp, series, subject ("Dividend - Rs 2 Per Share"), exDate, recDate, ...
  No params = only ~today's ex-dates, so ALWAYS pass the window (PAST_DAYS back for the
  "recent" view + FWD_DAYS forward for the calendar). STATELESS rebuild each run.

FALLBACK (2026-07-20, the day NSE hard-locked /api/* for every non-browser client): BSE's
forward corp-actions API (DefaultData/w, plain urllib + bseindia.com cookie warmup — the
CI-proven bse_fetch transport) honors the same Fdate/TDate window; scripcode -> NSE symbol
via scripts/bse_scrips.json, unmapped (BSE-only) scrips skipped to keep the page's NSE
universe. Purposes are dividend-heavy ("Final Dividend - Rs. - 1.6400" — note the dash the
amount regex must allow) but carry splits/bonus/buybacks too. Top-level "src" in the JSON
says which source built the file.

Enrichment: dividend amount parsed from the subject; yield% = amount / latest close
(dash_slim meta — ⚠️ '.NS'-keyed, re-key by bare symbol, runbook §26).

Output docs/actions.json:
  {"updated","from","to",
   "rows":[[exISO, sym, name, kind, subject, recISO|null, divAmt|null, yieldPct|null],...]}
  kind: D dividend | B bonus | S split | R rights | BB buyback | O other (AGM/EGM etc.)

Run: python -X utf8 scripts/fetch_actions.py
"""
import datetime
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
OUT = os.path.join(DOCS, "actions.json")
SLIM = os.path.join(DOCS, "dash_slim.bin")
PAST_DAYS, FWD_DAYS = 30, 75
MIN_ROWS = 10
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


def iso(s):
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})", str(s or "").strip())
    if not m:
        return None
    mo = MON.get(m.group(2).lower())
    return "%s-%02d-%02d" % (m.group(3), mo, int(m.group(1))) if mo else None


def kind_of(subject):
    s = str(subject or "").lower()
    if "dividend" in s:
        return "D"
    if "bonus" in s:
        return "B"
    if "split" in s or "sub-division" in s or "subdivision" in s or "sub division" in s:
        return "S"
    if "right" in s:
        return "R"
    if "buy back" in s or "buyback" in s or "buy-back" in s:
        return "BB"
    return "O"


def div_amt(subject):
    # allow BSE's "Rs. - 1.6400" spelling (dash between Rs. and the amount)
    m = re.search(r"r[se]\.?\s*-?\s*([\d]+(?:\.\d+)?)", str(subject or "").lower())
    return float(m.group(1)) if m else None


def fetch_nse(f, t):
    jar = B.nse_jar()
    hdr = {
        "User-Agent": B.UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
    }
    url = (
        "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
        "&from_date=%02d-%02d-%04d&to_date=%02d-%02d-%04d" % (f.day, f.month, f.year, t.day, t.month, t.year)
    )
    j = json.loads(B._get(url, headers=hdr, jar=jar, timeout=90))
    return j if isinstance(j, list) else (j.get("data") or [])


def fetch_bse(f, t):
    """BSE forward corp-actions -> NSE-shaped rows [{symbol, comp, subject, exDate?, _exISO, recDate?...}].
    Dates come back numeric (exdate=YYYYMMDD) / '20 Jul 2026' (RD_Date) — pre-ISO them into
    _exISO/_recISO so the main loop can use them without touching the NSE date parser."""
    import http.cookiejar
    import urllib.request

    def req(u):
        return urllib.request.Request(
            u,
            headers={
                "User-Agent": B.UA,
                "Accept": "*/*",
                "Referer": "https://www.bseindia.com/",
                "Origin": "https://www.bseindia.com",
            },
        )

    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with contextlib.suppress(Exception):
        op.open(req("https://www.bseindia.com/"), timeout=30).read()
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w?ddlcategorys=E&ddlindustrys="
        "&scripcode=&segment=0&strSearch=S&Fdate={}&TDate={}&Purposecode=".format(
            f.strftime("%Y%m%d"), t.strftime("%Y%m%d")
        )
    )
    r = op.open(req(url), timeout=60)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8", "replace"))
    rev = {
        int(v): k for k, v in json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"].items()
    }
    rows, unmapped = [], 0
    for x in data:
        sym = rev.get(int(x.get("scrip_code") or 0))
        if not sym:
            unmapped += 1
            continue
        ed = str(x.get("exdate") or "").strip()
        if not re.fullmatch(r"\d{8}", ed):
            continue
        rec = None
        m = re.match(r"^(\d{1,2}) ([A-Za-z]{3})\w* (\d{4})$", str(x.get("RD_Date") or "").strip())
        if m and MON.get(m.group(2).lower()):
            rec = "%s-%02d-%02d" % (m.group(3), MON[m.group(2).lower()], int(m.group(1)))
        rows.append(
            {
                "symbol": sym,
                "comp": x.get("long_name"),
                "subject": x.get("Purpose"),
                "_exISO": f"{ed[:4]}-{ed[4:6]}-{ed[6:]}",
                "_recISO": rec,
            }
        )
    print("BSE fallback: %d rows (%d BSE-only scrips skipped)" % (len(rows), unmapped), flush=True)
    return rows


def main():
    today = datetime.date.today()
    f = today - datetime.timedelta(days=PAST_DAYS)
    t = today + datetime.timedelta(days=FWD_DAYS)
    src = "NSE"
    try:
        data = fetch_nse(f, t)
    except Exception as ex:
        print(f"NSE fetch FAILED ({ex}) — trying the BSE calendar", flush=True)
        src = "BSE"
        try:
            data = fetch_bse(f, t)
        except Exception as ex2:
            print(f"BSE fallback FAILED too ({ex2}) — keeping the previous file", flush=True)
            sys.exit(1)
    if len(data) < MIN_ROWS:
        print("suspiciously few rows (%d) — keeping the previous file" % len(data), flush=True)
        sys.exit(1)

    meta = {}
    try:
        raw = json.loads(gzip.decompress(open(SLIM, "rb").read())).get("meta") or {}
        meta = {(v.get("symbol") or k.split(".")[0]).upper(): v for k, v in raw.items()}
    except Exception:
        print("WARN: dash_slim.bin unreadable — no yield enrichment", flush=True)

    rows, seen = [], set()
    for r in data:
        ex = r.get("_exISO") or iso(r.get("exDate"))
        sym = str(r.get("symbol") or "").strip().upper()
        subject = " ".join(str(r.get("subject") or "").split())
        if not (ex and sym and subject):
            continue
        key = (ex, sym, subject.lower())
        if key in seen:
            continue
        seen.add(key)
        k = kind_of(subject)
        amt = div_amt(subject) if k == "D" else None
        px = (meta.get(sym) or {}).get("latest")
        yld = round(amt / px * 100, 2) if (amt and px) else None
        rows.append(
            [ex, sym, str(r.get("comp") or "").strip(), k, subject, r.get("_recISO") or iso(r.get("recDate")), amt, yld]
        )
    rows.sort(key=lambda r: (r[0], r[1]))

    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    with open(OUT, "w", encoding="utf-8") as fo:
        json.dump(
            {
                "updated": ist.strftime("%Y-%m-%d %H:%M"),
                "from": f.isoformat(),
                "to": t.isoformat(),
                "src": src,
                "rows": rows,
            },
            fo,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    n_fut = sum(1 for r in rows if r[0] >= today.isoformat())
    import collections

    kinds = collections.Counter(r[3] for r in rows)
    print(
        "Wrote %s (%.0f KB): %d actions (%d upcoming) %s..%s | kinds %s"
        % (OUT, os.path.getsize(OUT) / 1024.0, len(rows), n_fut, f, t, dict(kinds)),
        flush=True,
    )
    for r in [r for r in rows if r[0] >= today.isoformat()][:5]:
        print("  {} {} {} {}{}".format(r[0], r[1], r[4][:40], (f"yield {r[7]:.1f}%") if r[7] else "", ""), flush=True)


if __name__ == "__main__":
    main()
