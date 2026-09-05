#!/usr/bin/env python3
"""Fetch India "Bank Loan Growth" (y/y) — the RBI bank-credit indicator.

This is the SAME indicator shown on Investing.com / TradingEconomics: the
year-on-year % change in outstanding bank credit of scheduled commercial banks,
published fortnightly by the Reserve Bank of India (compiled from ~39 banks that
cover ~90% of all loans). A rising number = banks lending more = stronger
borrowing/spending; it tracks the credit cycle and broad market regime.

SOURCE: mql5's economic-calendar `/export` endpoint returns the FULL history as a
clean TSV (Date / ActualValue / ForecastValue / PreviousValue) in a single
request — no API key, no Cloudflare challenge, reachable from GitHub runners
(RBI's own portal geo-blocks non-India IPs, so we don't depend on it). The feed is
cumulative, so we MERGE into docs/bank_credit.json and never shrink it: a skipped
run self-heals on the next one, and a finalized "actual" overwrites the earlier
provisional value for the same date.

stdlib only — no pip install needed in CI.
"""
import datetime
import json
import os
import sys
import urllib.request

URL = "https://www.mql5.com/en/economic-calendar/india/bank-loan-growth-yy/export"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "bank_credit.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch_tsv():
    req = urllib.request.Request(URL, headers={
        "User-Agent": UA,
        "Accept": "text/csv,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.mql5.com/en/economic-calendar/india/bank-loan-growth-yy",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _num(x):
    x = (x or "").strip().replace("%", "").replace(",", "")
    try:
        return round(float(x), 2)
    except ValueError:
        return None


def parse(tsv):
    rows = []
    for line in tsv.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("date"):
            continue
        p = line.split("\t")
        if len(p) < 2:
            continue
        date = p[0].strip().replace(".", "-").replace("/", "-")  # 2026.06.26 -> 2026-06-26
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            continue
        actual = _num(p[1])
        if actual is None:          # not-yet-released row — skip
            continue
        rows.append({
            "date": date,
            "actual": actual,
            "forecast": _num(p[2]) if len(p) > 2 else None,
            "previous": _num(p[3]) if len(p) > 3 else None,
        })
    return rows


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"rows": []}


def main():
    try:
        fresh = parse(fetch_tsv())
        print(f"fetched {len(fresh)} rows from mql5")
    except Exception as e:                       # network / parse failure -> keep existing
        print(f"WARN fetch/parse failed: {e}", file=sys.stderr)
        fresh = []

    by_date = {r["date"]: r for r in load_existing().get("rows", [])}
    added = 0
    for r in fresh:
        if r["date"] not in by_date:
            added += 1
        by_date[r["date"]] = r                   # newest fetch wins (finalized values)

    if not by_date:
        print("ERROR no data (fetch failed and no existing file) — not writing", file=sys.stderr)
        sys.exit(1)

    rows = sorted(by_date.values(), key=lambda r: r["date"])
    out = {
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Reserve Bank of India — Bank Loan Growth (y/y), fortnightly",
        "unit": "% y/y",
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    last = rows[-1]
    print(f"wrote {len(rows)} rows ({added} new) -> docs/bank_credit.json "
          f"| latest {last['date']} = {last['actual']}% y/y")


if __name__ == "__main__":
    main()
