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
"""Fetch the NSE IPO pipeline: UPCOMING issues, OPEN issues (with live subscription),
and RECENT LISTINGS (with issue price vs current price) -> docs/ipos.json for the
"IPOs & Listings" page.

SOURCES (urllib + cookie warmup — the announcements cron's CI-proven session):
  /api/all-upcoming-issues?category=ipo   {companyName,symbol,series EQ|SME,issueStartDate,
                                           issueEndDate,issuePrice "Rs.X to Rs.Y",issueSize(shares),status}
  /api/ipo-current-issue                  same + subscription: noOfTime (x subscribed, category Total)
  /api/public-past-issues                 full archive (~1.4k): company,symbol,securityType,ipoStartDate,
                                          ipoEndDate,listingDate,issuePrice(final),priceRange
  Current price + mcap for listed names come from dash_slim.bin meta —
  ⚠️ keyed 'RELIANCE.NS' (Yahoo suffix): re-key by bare symbol or every join misses (runbook §26).
  SME listings aren't in dash_slim -> shown without a current price (board chip says SME).

STATELESS: every run rebuilds from full snapshots (no merge/self-heal needed). Refuses to
write only when the past-issues archive comes back suspiciously small.

Output docs/ipos.json:
  {"updated",
   "upcoming":[[sym,name,board,openISO,closeISO,band,shares,status,subTimes|null],...],
   "listed":  [[sym,name,board,listISO,issuePrice,lastPx|null,mcapCr|null],...]}  # last LISTED_DAYS
Run: python -X utf8 scripts/fetch_ipos.py
"""
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
OUT = os.path.join(DOCS, "ipos.json")
SLIM = os.path.join(DOCS, "dash_slim.bin")
WORKER = (
    "https://stocksworld-quotes.dhruvan2510.workers.dev"  # live NSE quotes (Yahoo feed) — same source the page uses
)
LISTED_DAYS = 180
MIN_PAST = 100
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


def band(s):
    """'Rs.100 to Rs.105' -> '₹100–105'; 'Rs.214' -> '₹214'."""
    nums = re.findall(r"\d+(?:\.\d+)?", str(s or ""))
    if not nums:
        return str(s or "").strip()
    return "₹" + nums[0] + ("–" + nums[1] if len(nums) > 1 and nums[1] != nums[0] else "")


def to_num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def get(jar, ep, ref):
    hdr = {"User-Agent": B.UA, "Accept": "application/json, text/plain, */*", "Referer": ref}
    j = json.loads(B._get("https://www.nseindia.com/api/" + ep, headers=hdr, jar=jar, timeout=60))
    return j.get("data") if isinstance(j, dict) else j


def worker_quotes(syms):
    """Live LTP for NSE symbols via our Cloudflare Worker (Yahoo NSE feed) — the SAME
    source the IPO page uses at runtime, so the baked snapshot matches what viewers see.
    Freshly-listed names sit in dash_slim meta (they carry an mcap) but not its price
    series yet, so `latest` is null; this backfills their current price. Best-effort,
    batched ≤30/call (worker cap). URL-encoded so '&' symbols (M&M, J&KBANK) don't
    truncate the query (runbook: always url-encode symbol queries). Yahoo drops the odd
    symbol on a transient non-200, so still-missing names are retried (the ?symbols=
    route isn't cached, unlike ?quotes=) — a symbol absent after 3 passes is genuinely
    not on the feed (most SME). Returns {SYM: ltp}."""
    out = {}
    pending = list(dict.fromkeys(str(s).upper() for s in syms if s))
    for attempt in range(3):
        if not pending:
            break
        for i in range(0, len(pending), 30):
            grp = pending[i : i + 30]
            try:
                url = WORKER + "/?symbols=" + urllib.parse.quote(",".join(grp), safe="")
                j = json.loads(B._get(url, headers={"User-Agent": B.UA, "Accept": "application/json"}, timeout=30))
                for k, v in ((j or {}).get("data") or {}).items():
                    ltp = to_num(v.get("ltp"))
                    if ltp is not None:
                        out[str(k).upper()] = ltp
            except Exception as e:
                print(f"worker quotes batch failed ({grp[:2]}..): {e}", flush=True)
        pending = [s for s in pending if s not in out]
        if pending and attempt < 2:
            time.sleep(2)
    return out


def main():
    jar = B.nse_jar()
    ref_up = "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"
    up = cur = past = None
    try:
        up = get(jar, "all-upcoming-issues?category=ipo", ref_up) or []
    except Exception as e:
        print("upcoming FAILED:", e, flush=True)
    try:
        cur = get(jar, "ipo-current-issue", ref_up) or []
    except Exception as e:
        print("current FAILED:", e, flush=True)
    try:
        past = (
            get(jar, "public-past-issues", "https://www.nseindia.com/market-data/new-stock-exchange-listings-recent")
            or []
        )
    except Exception as e:
        print("past FAILED:", e, flush=True)
    if up is None and cur is None and past is None:
        print("ALL endpoints failed — keeping the previous file", flush=True)
        sys.exit(1)

    # subscription multiples from the open-issues call (category Total)
    subs = {}
    for r in cur or []:
        if str(r.get("category") or "Total") == "Total" and r.get("symbol"):
            subs[str(r["symbol"]).upper()] = to_num(r.get("noOfTime"))

    seen, upcoming = set(), []
    for r in (up or []) + (cur or []):
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        upcoming.append(
            [
                sym,
                str(r.get("companyName") or "").strip(),
                "SME" if "SME" in str(r.get("series") or "").upper() else "Main",
                iso(r.get("issueStartDate")),
                iso(r.get("issueEndDate")),
                band(r.get("issuePrice")),
                to_num(r.get("issueSize")),
                str(r.get("status") or "").strip(),
                round(subs[sym], 2) if subs.get(sym) is not None else None,
            ]
        )
    upcoming.sort(key=lambda r: (r[3] or "9999", r[0]))

    meta = {}
    try:
        raw = json.loads(gzip.decompress(open(SLIM, "rb").read())).get("meta") or {}
        meta = {(v.get("symbol") or k.split(".")[0]).upper(): v for k, v in raw.items()}
    except Exception:
        print("WARN: dash_slim.bin unreadable — listed rows carry no current price", flush=True)

    listed = []
    if past is not None:
        if len(past) < MIN_PAST:
            print("past-issues suspiciously small (%d) — keeping the previous file" % len(past), flush=True)
            sys.exit(1)
        lo = (datetime.date.today() - datetime.timedelta(days=LISTED_DAYS)).isoformat()
        for r in past:
            ld = iso(r.get("listingDate"))
            sym = str(r.get("symbol") or "").strip().upper()
            st = str(r.get("securityType") or "").strip().upper()
            # equity only: EQ + BE (new mainboard names often list in the T2T 'BE' series)
            # + SME; N0/Z9/RR/DEBT/IV are NCD/REIT/InvIT tranches, not stock listings
            if st not in ("EQ", "BE", "SME"):
                continue
            if not (ld and sym) or ld < lo:
                continue
            m = meta.get(sym) or {}
            listed.append(
                [
                    sym,
                    str(r.get("company") or "").strip(),
                    "SME" if "SME" in str(r.get("securityType") or "").upper() else "Main",
                    ld,
                    to_num(r.get("issuePrice")),
                    m.get("latest"),
                    round(m["mcap"], 1) if m.get("mcap") else None,
                ]
            )
        listed.sort(key=lambda r: r[3], reverse=True)

        # Freshly-listed names are in dash_slim meta (mcap) but not its daily price series
        # yet, so `now` bakes null and the page shows a blank Now / Since-issue until the
        # runtime JS fills it. Backfill those from the same live NSE feed so the EOD
        # snapshot isn't blank on load. (mcap stays as dash_slim provides it.)
        missing = [r[0] for r in listed if r[5] is None]
        if missing:
            live = worker_quotes(missing)
            n = 0
            for r in listed:
                if r[5] is None and live.get(r[0]) is not None:
                    r[5] = live[r[0]]
                    n += 1
            print("filled %d/%d missing listed prices from live feed" % (n, len(missing)), flush=True)

    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M"), "upcoming": upcoming, "listed": listed}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(
        "Wrote %s (%.0f KB): %d upcoming/open, %d listed in %dd"
        % (OUT, os.path.getsize(OUT) / 1024.0, len(upcoming), len(listed), LISTED_DAYS),
        flush=True,
    )
    for r in upcoming[:4]:
        print(f"  OPEN/UPCOMING {r[0]} {r[2]} {r[3]}..{r[4]} {r[5]} sub={r[8]}", flush=True)
    for r in listed[:3]:
        gain = (" %+.0f%%" % ((r[5] - r[4]) / r[4] * 100)) if (r[4] and r[5]) else ""
        print(f"  LISTED {r[0]} {r[2]} {r[3]} issue={r[4]} last={r[5]}{gain}", flush=True)


if __name__ == "__main__":
    main()
