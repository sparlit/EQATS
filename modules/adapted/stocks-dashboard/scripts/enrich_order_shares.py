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
"""Fill the market-cap gap for Order-Wins names that trade on NSE but never matched a BSE
market-cap in our universe (they show mcap "—", so no P/E either).

We can't read market cap from a live quote API (NSE quote = 403, Yahoo quote = 401), but we
already have the two pieces to COMPUTE it:
  • shares outstanding  = PaidUpValueOfEquityShareCapital / FaceValue  (from the company's
    own NSE integrated-filing iXBRL — the same filings the fundamentals cron already pulls)
  • latest price        = dash_slim meta[SYM.NS].latest  (already on disk)
  mcap (₹cr) = shares × price / 1e7.  Validated vs known names (SURYAROSNI 5613.9 → 5609.7,
  KERNEX 3454.3 → 3454.9).

Share count changes rarely, so we cache SHARES (not mcap) — build_discovery multiplies by the
current price each build, keeping mcap fresh without re-fetching XBRL.

  out: docs/order_shares.json  {updated, shares:{SYM: <count>}}   ("" = checked, none found)

Run: python -X utf8 scripts/enrich_order_shares.py   (CI: refresh-announcements.yml, before build_discovery)
"""
import datetime
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B

HERE = os.path.dirname(os.path.abspath(__file__))


def dp(f):
    return os.path.join(HERE, "..", "docs", f)


OUT = dp("order_shares.json")
ORDER_RX = re.compile(r"orders?/contracts|order\(s\)\/contract", re.IGNORECASE)
H = {"User-Agent": B.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
RE_PU = re.compile(r"PaidUpValueOfEquityShareCapital[^>]*>([^<]+)<")
RE_FV = re.compile(r"FaceValueOfEquityShareCapital[^>]*>([^<]+)<")


def yahoo_price(sym):
    """Latest price for names our own price file doesn't cover (NSE .NS via Yahoo's chart
    endpoint — the one Yahoo route still open without a crumb)."""
    import urllib.request

    try:
        req = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?range=1d&interval=1d",
            headers={"User-Agent": B.UA},
        )
        j = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        return j["chart"]["result"][0]["meta"].get("regularMarketPrice")
    except Exception:
        return None


def shares_from_xbrl(sym, jar):
    jb = json.loads(
        B._get(
            f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={sym}&period=Quarterly",
            headers=H,
            jar=jar,
            timeout=40,
        )
    )
    rows = jb if isinstance(jb, list) else jb.get("data", [])
    for r in rows:
        u = r.get("xbrl", "")
        if not u.startswith("http"):
            continue
        try:
            xml = B._get(u, headers={"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}, timeout=40)
        except Exception:
            continue
        pu, fv = RE_PU.search(xml), RE_FV.search(xml)
        if pu and fv:
            try:
                p, f = float(pu.group(1)), float(fv.group(1))
                if f > 0 and p > 0:
                    return round(p / f)
            except Exception:
                pass
    return None


def main():
    ann = json.load(open(dp("announcements.json"), encoding="utf-8"))
    slim = json.loads(gzip.decompress(open(dp("dash_slim.bin"), "rb").read()))
    # key by symbol exactly as build_discovery does, so "has a market cap?" agrees with the page
    META = {}
    for k, m in (slim.get("meta") or {}).items():
        sym = str(m.get("symbol") or k.split(".")[0]).upper()
        META[sym] = {"mcap": m.get("mcap"), "latest": m.get("latest")}

    def mc_of(sym):
        return (META.get(sym) or {}).get("mcap")

    def px_of(sym):
        return (META.get(sym) or {}).get("latest")

    # order-win symbols that lack a market cap (mcap is computable = shares × price; price from our
    # own file when we have it, else Yahoo)
    gap = set()
    for r in ann.get("rows", []):
        sym, _co, _dt, desc, _cap, _f = r
        if ORDER_RX.search(desc) and not mc_of(sym):
            gap.add(sym)

    cache = {}
    if os.path.exists(OUT):
        try:
            cache = json.load(open(OUT, encoding="utf-8")).get("shares", {})
        except Exception as ex:
            print("WARN cache unreadable:", ex)

    todo = [s for s in sorted(gap) if s not in cache]
    print("mcap-gap order names: %d (%d cached, %d to fetch)" % (len(gap), len(gap) - len(todo), len(todo)))
    jar = None
    ok = miss = err = 0
    for sym in todo:
        if jar is None:
            jar = B.nse_jar()
        try:
            n = shares_from_xbrl(sym, jar)
            if not n:
                cache[sym] = ""
                miss += 1
                continue
            # price: prefer our own file; for names it doesn't cover, fetch Yahoo and store it
            p = px_of(sym)
            ypx = None if p else yahoo_price(sym)
            cache[sym] = {"sh": n, "px": ypx}  # px null when our file already has the price
            use = p or ypx
            ok += 1
            print(
                "  OK   %-12s shares=%s  price=%s  mcap≈%s"
                % (sym, n, use, ("%.1f cr" % (n * use / 1e7)) if use else "— (no price)")
            )
        except Exception as ex:
            err += 1
            print("  ERR  %-12s %s" % (sym, repr(ex)[:60]))  # not cached -> retried next run

    for s in [k for k in cache if k not in gap]:  # prune names that left the window / gained a mcap
        del cache[s]

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    json.dump(
        {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "shares": cache},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    print(
        "WROTE %s: %d names with shares (fetched OK %d / miss %d / err %d)"
        % (os.path.normpath(OUT), sum(1 for v in cache.values() if v), ok, miss, err)
    )


if __name__ == "__main__":
    main()
