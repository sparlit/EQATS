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


#!/usr/bin/env python3
"""
NSE Pre-Open F&O + Equity Derivatives Watch Dashboard
=====================================================
Fetches two NSE feeds, builds one HTML dashboard, and can either write a static
snapshot (for a 9:15 AM daily job) or run a live local server that auto-refreshes
every 5 minutes.

    python nse_dashboard.py            # fetch once, write dashboard.html (+ history)
    python nse_dashboard.py --serve    # live server at http://localhost:8000, 5-min refresh
    python nse_dashboard.py --demo     # build dashboard.html from sample data (no network)
    python nse_dashboard.py --serve --port 8080

Data sources
------------
1. Pre-open F&O   : /api/market-data-pre-open?key=FO
2. Derivatives    : /api/liveEquity-derivatives?index=<category>
   The index= category names below are NSE's and occasionally change. If a
   category comes back empty, open the equity-derivatives-watch page, open your
   browser's Network tab, and copy the exact index= value NSE requests.

Files (next to this script): dashboard.html, latest_raw.json, pre_open_history.csv
"""

import argparse
import contextlib
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_OUT = os.path.join(OUT_DIR, "dashboard.html")
DOCS_DIR = os.path.join(OUT_DIR, "docs")  # what gets published to the web
DOCS_INDEX = os.path.join(DOCS_DIR, "index.html")
RAW_JSON = os.path.join(OUT_DIR, "latest_raw.json")
HISTORY_CSV = os.path.join(OUT_DIR, "pre_open_history.csv")

# Shell command run after each successful build to publish docs/ (git push, netlify deploy…).
# Set via --publish or the NSE_PUBLISH_CMD environment variable.
PUBLISH_CMD = os.environ.get("NSE_PUBLISH_CMD", "")

BASE = "https://www.nseindia.com"
PAGE_PREOPEN = "https://www.nseindia.com/market-data/pre-open-market-fno"
PAGE_DERIV = "https://www.nseindia.com/market-data/equity-derivatives-watch"
PAGE_OI = "https://www.nseindia.com/market-data/oi-spurts"
PREOPEN_API = "https://www.nseindia.com/api/market-data-pre-open?key=FO"
DERIV_API = "https://www.nseindia.com/api/liveEquity-derivatives?index={cat}"
OI_API = "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings"

# (index= value, display label). Adjust if a category returns empty. Order = dropdown order.
DERIV_CATEGORIES = [
    ("nifty50_fut", "Nifty 50 Futures"),
    ("niftybank_fut", "Nifty Bank Futures"),
    ("top20_futures_contracts", "Top 20 Futures Contracts"),
]

REFRESH_SECS = 300  # 5 minutes

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
def new_session():
    import requests

    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(BASE, timeout=15)
        time.sleep(0.8)
        s.get(PAGE_PREOPEN, timeout=15)
        time.sleep(0.4)
    except Exception as e:
        print(f"[warn] cookie priming failed ({e})")
    return s


def get_json(s, url, referer, retries=4, pause=2.0):
    last = None
    for i in range(1, retries + 1):
        try:
            r = s.get(url, headers={"Referer": referer}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            print(f"[warn] {url} attempt {i}/{retries}: {e}")
            time.sleep(pause * i)
            with contextlib.suppress(Exception):
                s.get(BASE, timeout=15)
    msg = f"{url} failed after {retries} tries: {last}"
    raise RuntimeError(msg)


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _num(*vals):
    for v in vals:
        if v in (None, "", "-"):
            continue
        try:
            return float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            continue
    return None


def parse_preopen(raw):
    rows = []
    for item in raw.get("data", []):
        md = item.get("metadata", {}) or {}
        detail = (item.get("detail", {}) or {}).get("preOpenMarket", {}) or {}
        sym = md.get("symbol") or item.get("symbol")
        if not sym:
            continue
        rows.append(
            {
                "symbol": sym,
                "iep": _num(md.get("lastPrice"), detail.get("IEP"), detail.get("iep")),
                "change": _num(md.get("change"), detail.get("Change")),
                "pChange": _num(md.get("pChange"), detail.get("perChange")),
                "prevClose": _num(md.get("previousClose"), detail.get("previousClose")),
                "finalQty": _num(md.get("finalQuantity"), detail.get("finalQuantity")),
                "turnover": _num(md.get("totalTurnover"), detail.get("totalTurnover")),
            }
        )
    summary = {
        "advances": raw.get("advances"),
        "declines": raw.get("declines"),
        "unchanged": raw.get("unchanged"),
        "total": len(rows),
    }
    if summary["advances"] is None:
        summary["advances"] = sum(1 for r in rows if (r["pChange"] or 0) > 0)
        summary["declines"] = sum(1 for r in rows if (r["pChange"] or 0) < 0)
        summary["unchanged"] = sum(1 for r in rows if (r["pChange"] or 0) == 0)
    return rows, summary


def parse_deriv(raw):
    rows = []
    for d in raw.get("data", []):
        under = d.get("underlying") or d.get("symbol")
        if not under:
            continue
        rows.append(
            {
                "symbol": under,
                "expiry": d.get("expiryDate") or "-",
                "ltp": _num(d.get("lastPrice")),
                "change": _num(d.get("change")),
                "pChange": _num(d.get("pChange")),
                "volume": _num(d.get("numberOfContractsTraded"), d.get("volume")),
                "turnover": _num(d.get("totalTurnover")),
                "oi": _num(d.get("openInterest"), d.get("openInterestValue")),
            }
        )
    meta = {
        "underlyingValue": _num(raw.get("underlyingValue")),
        "timestamp": raw.get("timestamp") or raw.get("time"),
    }
    return rows, meta


def parse_oispurts(raw):
    rows = []
    for d in raw.get("data", []):
        sym = d.get("symbol") or d.get("underlying")
        if not sym:
            continue
        oi_pct = _num(d.get("avgInOI"), d.get("percentChangeInOI"), d.get("changeInOIPer"))
        if oi_pct is None:
            latest, prev = _num(d.get("latestOI")), _num(d.get("prevOI"))
            if latest is not None and prev not in (None, 0):
                oi_pct = round((latest - prev) / prev * 100, 2)
        rows.append(
            {
                "symbol": sym,
                "oiPct": oi_pct,
                "pricePct": _num(d.get("pChange"), d.get("perChange"), d.get("percentChange")),
                "ltp": _num(d.get("ltp"), d.get("lastPrice"), d.get("underlyingValue")),
                "changeInOI": _num(d.get("changeInOI")),
                "volume": _num(d.get("volume"), d.get("tradedVolume")),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# History (one pre-open snapshot per day)
# --------------------------------------------------------------------------- #
def append_history(rows, stamp):
    day = stamp.strftime("%Y-%m-%d")
    seen = set()
    if os.path.exists(HISTORY_CSV):
        with open(HISTORY_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen.add(r.get("date"))
    if day in seen:
        return False
    fields = ["date", "symbol", "iep", "change", "pChange", "prevClose", "finalQty", "turnover"]
    new = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({"date": day, **r})
    return True


# --------------------------------------------------------------------------- #
# Payload assembly
# --------------------------------------------------------------------------- #
def build_payload(preopen_rows, preopen_summary, deriv_cats, oispurts_rows, stamp, note=None):
    return {
        "preopen": {"rows": preopen_rows, "summary": preopen_summary},
        "deriv": deriv_cats,  # list of {key,label,rows,meta}
        "oispurts": {"rows": oispurts_rows or []},
        "updated": stamp.strftime("%d %b %Y, %I:%M:%S %p IST"),
        "refreshSecs": REFRESH_SECS,
        "note": note,
    }


def gather_live(stamp=None, write=True):
    """Fetch both feeds. Raises if the pre-open feed can't be read at all."""
    stamp = stamp or datetime.now()
    s = new_session()
    preopen_raw = get_json(s, PREOPEN_API, PAGE_PREOPEN)
    if not preopen_raw.get("data"):
        msg = "pre-open API returned no data"
        raise RuntimeError(msg)
    p_rows, p_sum = parse_preopen(preopen_raw)

    deriv_cats = []
    for key, label in DERIV_CATEGORIES:
        try:
            raw = get_json(s, DERIV_API.format(cat=key), PAGE_DERIV, retries=2)
            rows, meta = parse_deriv(raw)
            if rows:
                deriv_cats.append({"key": key, "label": label, "rows": rows, "meta": meta})
        except Exception as e:
            print(f"[warn] derivatives '{key}' skipped: {e}")

    oi_rows = []
    try:
        oi_raw = get_json(s, OI_API, PAGE_OI, retries=2)
        oi_rows = parse_oispurts(oi_raw)
    except Exception as e:
        print(f"[warn] oi-spurts skipped: {e}")

    note = None
    if not deriv_cats and not oi_rows:
        note = (
            "Derivatives and OI-spurts feeds both returned empty — their API names "
            "may need updating (see the file header)."
        )
    elif not deriv_cats:
        note = (
            "Derivatives-watch categories returned empty — the index= names in "
            "DERIV_CATEGORIES likely need updating (see the file header)."
        )
    elif not oi_rows:
        note = "OI-spurts feed returned empty — check the OI_API endpoint (see the file header)."

    if write:
        with open(RAW_JSON, "w", encoding="utf-8") as f:
            json.dump({"preopen": preopen_raw}, f, indent=2)
        append_history(p_rows, stamp)

    return build_payload(p_rows, p_sum, deriv_cats, oi_rows, stamp, note)


# --------------------------------------------------------------------------- #
# Sample data
# --------------------------------------------------------------------------- #
def sample_payload():
    base = [
        ("RELIANCE", 2942.5, 2901.0),
        ("TCS", 3888.0, 3925.4),
        ("HDFCBANK", 1680.2, 1662.1),
        ("INFY", 1544.9, 1571.0),
        ("ICICIBANK", 1245.6, 1230.0),
        ("SBIN", 842.3, 828.7),
        ("TATAMOTORS", 978.4, 1002.5),
        ("TATASTEEL", 168.9, 165.4),
        ("AXISBANK", 1176.0, 1188.9),
        ("BAJFINANCE", 7210.5, 7095.0),
        ("MARUTI", 12840.0, 12990.0),
        ("HINDALCO", 655.2, 641.8),
        ("LT", 3620.0, 3588.5),
        ("ITC", 468.7, 471.2),
        ("WIPRO", 552.1, 545.0),
        ("KOTAKBANK", 1795.0, 1812.3),
        ("SUNPHARMA", 1855.4, 1830.0),
        ("ADANIENT", 2410.0, 2477.5),
        ("BHARTIARTL", 1590.5, 1566.0),
        ("HCLTECH", 1720.0, 1740.9),
    ]
    p_rows = []
    for sym, iep, prev in base:
        chg = round(iep - prev, 2)
        pc = round(chg / prev * 100, 2)
        qty = int(abs(chg) * 5300 + 12000)
        p_rows.append(
            {
                "symbol": sym,
                "iep": iep,
                "change": chg,
                "pChange": pc,
                "prevClose": prev,
                "finalQty": qty,
                "turnover": round(iep * qty / 1e7, 2),
            }
        )
    p_sum = {
        "advances": sum(1 for r in p_rows if r["pChange"] > 0),
        "declines": sum(1 for r in p_rows if r["pChange"] < 0),
        "unchanged": sum(1 for r in p_rows if r["pChange"] == 0),
        "total": len(p_rows),
    }

    def fut(sym, exp, ltp, prev, vol, oi):
        chg = round(ltp - prev, 2)
        pc = round(chg / prev * 100, 2)
        return {
            "symbol": sym,
            "expiry": exp,
            "ltp": ltp,
            "change": chg,
            "pChange": pc,
            "volume": vol,
            "turnover": round(ltp * vol / 1e5, 2),
            "oi": oi,
        }

    idx = [
        fut("NIFTY", "26-Jun-2025", 23145.0, 23010.5, 214530, 12800000),
        fut("NIFTY", "31-Jul-2025", 23198.0, 23070.0, 41220, 3100000),
        fut("BANKNIFTY", "26-Jun-2025", 50210.0, 49880.0, 132900, 3900000),
        fut("FINNIFTY", "26-Jun-2025", 23640.0, 23555.0, 28840, 990000),
    ]
    stk = [
        fut("RELIANCE", "26-Jun-2025", 2945.0, 2901.0, 88420, 5120000),
        fut("TCS", "26-Jun-2025", 3886.0, 3925.4, 41010, 2210000),
        fut("HDFCBANK", "26-Jun-2025", 1681.0, 1662.1, 97650, 6640000),
        fut("SBIN", "26-Jun-2025", 843.0, 828.7, 120340, 8810000),
        fut("INFY", "26-Jun-2025", 1543.0, 1571.0, 55220, 3300000),
        fut("TATAMOTORS", "26-Jun-2025", 977.0, 1002.5, 76110, 4450000),
    ]
    deriv = [
        {
            "key": "nifty50_fut",
            "label": "Nifty 50 Futures",
            "rows": idx,
            "meta": {"underlyingValue": 23138.5, "timestamp": "sample"},
        },
        {
            "key": "top20_futures_contracts",
            "label": "Top 20 Futures Contracts",
            "rows": idx + stk,
            "meta": {"underlyingValue": None, "timestamp": "sample"},
        },
    ]
    oi = [
        {"symbol": "RELIANCE", "oiPct": 8.4, "pricePct": 1.51, "ltp": 2945.0, "changeInOI": 410000, "volume": 88420},
        {"symbol": "SBIN", "oiPct": 12.7, "pricePct": 1.70, "ltp": 843.0, "changeInOI": 980000, "volume": 120340},
        {"symbol": "HDFCBANK", "oiPct": 5.1, "pricePct": 1.12, "ltp": 1681.0, "changeInOI": 260000, "volume": 97650},
        {"symbol": "TCS", "oiPct": -4.6, "pricePct": -0.99, "ltp": 3886.0, "changeInOI": -120000, "volume": 41010},
        {"symbol": "INFY", "oiPct": -7.2, "pricePct": -1.78, "ltp": 1543.0, "changeInOI": -230000, "volume": 55220},
        {"symbol": "TATAMOTORS", "oiPct": 15.3, "pricePct": -2.51, "ltp": 977.0, "changeInOI": 640000, "volume": 76110},
        {"symbol": "TATASTEEL", "oiPct": 9.8, "pricePct": 2.10, "ltp": 168.9, "changeInOI": 1500000, "volume": 210300},
        {
            "symbol": "ADANIENT",
            "oiPct": -11.4,
            "pricePct": -2.70,
            "ltp": 2410.0,
            "changeInOI": -180000,
            "volume": 62110,
        },
        {"symbol": "AXISBANK", "oiPct": 3.2, "pricePct": -1.05, "ltp": 1176.0, "changeInOI": 90000, "volume": 71230},
    ]
    return build_payload(
        p_rows, p_sum, deriv, oi, datetime.now(), note="Sample data — run without --demo for live NSE numbers."
    )


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render_from_payload(payload):
    data_json = json.dumps(payload, separators=(",", ":"))
    return HTML_TEMPLATE.replace("/*__DATA__*/null", data_json)


def write_html(payload):
    html = render_from_payload(payload)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    os.makedirs(DOCS_DIR, exist_ok=True)  # public copy for hosting
    with open(DOCS_INDEX, "w", encoding="utf-8") as f:
        f.write(html)
    return HTML_OUT


def publish():
    """Run the configured publish command (git push / netlify deploy) from OUT_DIR."""
    if not PUBLISH_CMD:
        return
    try:
        r = subprocess.run(PUBLISH_CMD, shell=True, cwd=OUT_DIR, capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            print("[publish] ok")
        else:
            print(f"[publish] failed: {(r.stderr or r.stdout).strip()[:300]}")
    except Exception as e:
        print(f"[publish] error: {e}")


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #
_cache = {"ts": 0.0, "html": None}


def cached_html():
    now = time.time()
    if _cache["html"] and now - _cache["ts"] < REFRESH_SECS:
        return _cache["html"]
    try:
        payload = gather_live()
        write_html(payload)
        publish()
        html = render_from_payload(payload)
    except Exception as e:
        if _cache["html"]:
            print(f"[warn] refresh failed, serving cached: {e}")
            return _cache["html"]
        payload = build_payload(
            [],
            {"advances": 0, "declines": 0, "unchanged": 0, "total": 0},
            [],
            [],
            datetime.now(),
            note=f"Could not fetch NSE: {e}",
        )
        html = render_from_payload(payload)
    _cache.update(ts=now, html=html)
    return html


def serve(port):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html", "/dashboard.html"):
                self.send_response(404)
                self.end_headers()
                return
            body = cached_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[ok] live dashboard: http://localhost:{port}  (refresh every {REFRESH_SECS // 60} min, Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bye]")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="NSE pre-open + derivatives dashboard")
    ap.add_argument("--serve", action="store_true", help="run live server, auto-refresh every 5 min")
    ap.add_argument("--demo", action="store_true", help="build from sample data, no network")
    ap.add_argument("--publish", metavar="CMD", help="shell command to run after each build (e.g. publish_github.bat)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    global PUBLISH_CMD
    if args.publish:
        PUBLISH_CMD = args.publish

    if args.demo:
        write_html(sample_payload())
        print(f"[demo] dashboard -> {HTML_OUT}")
        return
    if args.serve:
        serve(args.port)
        return

    try:
        payload = gather_live()
    except Exception as e:
        print(
            f"[error] {e}\n[error] NSE unreachable (rate-limit, no internet, or VPN). "
            "Existing dashboard.html keeps the last data."
        )
        sys.exit(1)
    write_html(payload)
    publish()
    n = len(payload["preopen"]["rows"])
    d = sum(len(c["rows"]) for c in payload["deriv"])
    print(f"[ok] pre-open {n} symbols, derivatives {d} contracts -> {HTML_OUT}")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>NSE F&amp;O Board</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Expanded:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#0f1216; --panel:#171b21; --panel-2:#1d222a; --line:#282f3a;
    --text:#e8ebef; --muted:#8a94a3; --dim:#5d6675;
    --amber:#f0b429; --amber-soft:#3a2f14;
    --up:#2fbf71; --up-soft:#123522; --down:#f0526b; --down-soft:#3a1620; --flat:#6b7688;
  }
  *{box-sizing:border-box}
  body{margin:0; background:var(--ink); color:var(--text);
    font-family:"Inter",system-ui,sans-serif; font-size:14px; line-height:1.4}
  .wrap{max-width:1100px; margin:0 auto; padding:22px 18px 64px}
  header{display:flex; align-items:flex-end; justify-content:space-between; gap:16px;
    flex-wrap:wrap; border-bottom:1px solid var(--line); padding-bottom:16px; margin-bottom:20px}
  .brand{display:flex; align-items:baseline; gap:12px; flex-wrap:wrap}
  .tick{color:var(--amber); font-family:"IBM Plex Mono",monospace; font-weight:600;
    letter-spacing:.14em; font-size:11px; text-transform:uppercase}
  h1{font-family:"Archivo Expanded","Inter",sans-serif; font-weight:800; font-size:26px;
    letter-spacing:-.01em; margin:0; line-height:1}
  .sub{color:var(--muted); font-size:12px; margin-top:6px; font-family:"IBM Plex Mono",monospace}
  .meta{text-align:right; color:var(--muted); font-size:12px; font-family:"IBM Plex Mono",monospace}
  .meta b{color:var(--text); font-weight:600}
  .cd{color:var(--amber)}
  .note{margin:0 0 8px; padding:10px 13px; background:var(--amber-soft);
    border:1px solid #5a4a1e; border-radius:8px; color:#f4d68a; font-size:12.5px;
    font-family:"IBM Plex Mono",monospace}
  .sec{margin:30px 0 14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap}
  .sec .no{font-family:"IBM Plex Mono",monospace; color:var(--amber); font-size:12px; font-weight:600}
  .sec h2{font-family:"Archivo Expanded",sans-serif; font-weight:700; font-size:15px;
    letter-spacing:.02em; margin:0; text-transform:uppercase}
  .sec .hint{color:var(--dim); font-size:12px; margin-left:auto; font-family:"IBM Plex Mono",monospace}
  .movers{display:grid; grid-template-columns:1fr 1fr; gap:16px}
  @media(max-width:680px){.movers{grid-template-columns:1fr}}
  .card{background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden}
  .card h3{margin:0; padding:11px 14px; font-size:11px; letter-spacing:.14em; text-transform:uppercase;
    font-family:"IBM Plex Mono",monospace; border-bottom:1px solid var(--line);
    display:flex; justify-content:space-between; align-items:center}
  .card h3 .n{color:var(--dim); font-weight:400; letter-spacing:0}
  .card.up h3{color:var(--up); background:var(--up-soft)}
  .card.down h3{color:var(--down); background:var(--down-soft)}
  .mv{display:flex; align-items:center; justify-content:space-between; padding:9px 14px;
    border-bottom:1px solid var(--line)}
  .mv:last-child{border-bottom:0}
  .mv .s{font-weight:600; font-size:13px}
  .mv .s em{color:var(--dim); font-style:normal; font-weight:400; font-size:11px;
    margin-left:7px; font-family:"IBM Plex Mono",monospace}
  .mv .p{font-family:"IBM Plex Mono",monospace; font-size:12px; color:var(--muted);
    margin-left:auto; margin-right:14px}
  .mv .pc{font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:13px;
    min-width:74px; text-align:right}
  .pos{color:var(--up)} .neg{color:var(--down)} .zer{color:var(--flat)}
  .pair{display:flex; align-items:baseline; gap:5px; margin-left:auto; flex-wrap:wrap; justify-content:flex-end}
  .pair .lab{color:var(--dim); font-size:10px; font-family:"IBM Plex Mono",monospace;
    text-transform:uppercase; letter-spacing:.04em}
  .pair .pc{min-width:58px; text-align:right}
  .pair .pc + .lab{margin-left:8px}
  .mv.empty{color:var(--dim); font-family:"IBM Plex Mono",monospace; justify-content:center}
  .scroll{max-height:540px; overflow-y:auto}
  .scroll::-webkit-scrollbar{width:8px}
  .scroll::-webkit-scrollbar-thumb{background:var(--line); border-radius:4px}
  footer{margin-top:34px; color:var(--dim); font-size:11.5px; line-height:1.6;
    font-family:"IBM Plex Mono",monospace; border-top:1px solid var(--line); padding-top:16px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="brand"><span class="tick">● Live Tape</span><h1>NSE F&amp;O Board</h1></div>
      <div class="sub">Common (all 3) at top · full up/down for pre-open, derivatives &amp; OI spurts</div>
    </div>
    <div class="meta">Updated <b id="updated">—</b><br>Next refresh <span class="cd" id="cd">05:00</span></div>
  </header>

  <div id="note" class="note" style="display:none"></div>

  <div class="sec"><span class="no">01</span><h2>Common — In All 3 Feeds</h2>
    <span class="hint">pre-open · futures · OI change %</span></div>
  <div class="movers">
    <div class="card up"><h3>Increase <span class="n" id="com-up-n"></span></h3><div class="scroll" id="com-gainers"></div></div>
    <div class="card down"><h3>Decrease <span class="n" id="com-dn-n"></span></h3><div class="scroll" id="com-losers"></div></div>
  </div>

  <div class="sec"><span class="no">02</span><h2>Pre-Open F&amp;O — All</h2>
    <span class="hint">indicative % vs prev close</span></div>
  <div class="movers">
    <div class="card up"><h3>Increase <span class="n" id="pre-up-n"></span></h3><div class="scroll" id="pre-gainers"></div></div>
    <div class="card down"><h3>Decrease <span class="n" id="pre-dn-n"></span></h3><div class="scroll" id="pre-losers"></div></div>
  </div>

  <div class="sec"><span class="no">03</span><h2>Equity Derivatives — All</h2>
    <span class="hint">live futures · % vs prev close</span></div>
  <div class="movers">
    <div class="card up"><h3>Increase <span class="n" id="der-up-n"></span></h3><div class="scroll" id="der-gainers"></div></div>
    <div class="card down"><h3>Decrease <span class="n" id="der-dn-n"></span></h3><div class="scroll" id="der-losers"></div></div>
  </div>

  <div class="sec"><span class="no">04</span><h2>OI Spurts — All</h2>
    <span class="hint">Px = price % · OI = open-interest change %</span></div>
  <div class="movers">
    <div class="card up"><h3>OI Build-up <span class="n" id="oi-up-n"></span></h3><div class="scroll" id="oi-gainers"></div></div>
    <div class="card down"><h3>OI Unwind <span class="n" id="oi-dn-n"></span></h3><div class="scroll" id="oi-losers"></div></div>
  </div>

  <footer>
    Source: NSE pre-open market (F&amp;O) &amp; equity derivatives watch. Indicative /
    delayed values — not investment advice. Page auto-refreshes every 5 minutes.
  </footer>
</div>

<script>
const PAYLOAD = /*__DATA__*/null;
const num=(n,d=2)=>(n===null||n===undefined||isNaN(n))?"—":Number(n).toLocaleString("en-IN",{minimumFractionDigits:d,maximumFractionDigits:d});
const cc=n=>n>0?"pos":n<0?"neg":"zer";
const sg=n=>n>0?"+":"";
const mmss=s=>String(Math.floor(s/60)).padStart(2,"0")+":"+String(s%60).padStart(2,"0");
const TOP=10;

function fmtDate(x){ // "26-Jun-2025" -> "26 Jun"
  if(!x||x==="-") return "";
  const p=String(x).split("-"); return p.length>=2 ? p[0]+" "+p[1] : x;
}
function splitMovers(rows){
  const wp=rows.filter(r=>r.pChange!=null);
  const up=wp.filter(r=>r.pChange>0).sort((a,b)=>b.pChange-a.pChange);
  const dn=wp.filter(r=>r.pChange<0).sort((a,b)=>a.pChange-b.pChange);
  return {up,dn,upN:up.length,dnN:dn.length};
}
function row(sym,exp,price,pc){
  const e = exp?`<em>${fmtDate(exp)}</em>`:"";
  return `<div class="mv"><span class="s">${sym}${e}</span>`+
         `<span class="p">₹${num(price)}</span>`+
         `<span class="pc ${cc(pc)}">${sg(pc)}${num(pc)}%</span></div>`;
}
function pairRow(sym, pairs){
  const inner = pairs.map(p=>`<span class="lab">${p.lab}</span><span class="pc ${cc(p.v)}">${p.v==null?"—":sg(p.v)+num(p.v)+"%"}</span>`).join("");
  return `<div class="mv"><span class="s">${sym}</span><span class="pair">${inner}</span></div>`;
}
function fill(id, html){ document.getElementById(id).innerHTML = html || '<div class="mv empty">—</div>'; }

function boot(){
  if(!PAYLOAD) return;
  document.getElementById("updated").textContent=PAYLOAD.updated||"—";
  if(PAYLOAD.note){const n=document.getElementById("note"); n.style.display="block"; n.textContent=PAYLOAD.note;}

  // Build lookup maps keyed by symbol
  const preMap=new Map();
  (PAYLOAD.preopen.rows||[]).forEach(r=>{ if(r.pChange!=null) preMap.set(r.symbol,r); });
  const derMap=new Map();  // near-month per underlying (first row seen)
  (PAYLOAD.deriv||[]).forEach(c=>(c.rows||[]).forEach(r=>{
    if(r.pChange!=null && !derMap.has(r.symbol)) derMap.set(r.symbol,r);
  }));
  const oiMap=new Map();
  ((PAYLOAD.oispurts&&PAYLOAD.oispurts.rows)||[]).forEach(r=>{ if(!oiMap.has(r.symbol)) oiMap.set(r.symbol,r); });

  // Common = symbols present in ALL THREE feeds
  const common=[];
  preMap.forEach((p,sym)=>{
    if(derMap.has(sym) && oiMap.has(sym)){
      common.push({symbol:sym, prePc:p.pChange, futPc:derMap.get(sym).pChange, oiPc:oiMap.get(sym).oiPct});
    }
  });
  const cUp=common.filter(x=>x.prePc>0).sort((a,b)=>b.prePc-a.prePc);
  const cDn=common.filter(x=>x.prePc<0).sort((a,b)=>a.prePc-b.prePc);
  document.getElementById("com-up-n").textContent=cUp.length;
  document.getElementById("com-dn-n").textContent=cDn.length;
  const crow=x=>pairRow(x.symbol,[{lab:"Pre",v:x.prePc},{lab:"Fut",v:x.futPc},{lab:"OI",v:x.oiPc}]);
  fill("com-gainers", cUp.map(crow).join(""));
  fill("com-losers",  cDn.map(crow).join(""));

  // Pre-Open F&O — all up / all down
  const pm=splitMovers(PAYLOAD.preopen.rows||[]);
  document.getElementById("pre-up-n").textContent=pm.upN;
  document.getElementById("pre-dn-n").textContent=pm.dnN;
  fill("pre-gainers", pm.up.map(r=>row(r.symbol,null,r.iep,r.pChange)).join(""));
  fill("pre-losers",  pm.dn.map(r=>row(r.symbol,null,r.iep,r.pChange)).join(""));

  // Equity Derivatives — all up / all down (dedupe by symbol+expiry)
  const seen=new Set(), pool=[];
  (PAYLOAD.deriv||[]).forEach(c=>(c.rows||[]).forEach(r=>{
    const k=r.symbol+"|"+r.expiry;
    if(!seen.has(k)){seen.add(k); pool.push(r);}
  }));
  const dm=splitMovers(pool);
  document.getElementById("der-up-n").textContent=dm.upN;
  document.getElementById("der-dn-n").textContent=dm.dnN;
  fill("der-gainers", dm.up.map(r=>row(r.symbol,r.expiry,r.ltp,r.pChange)).join(""));
  fill("der-losers",  dm.dn.map(r=>row(r.symbol,r.expiry,r.ltp,r.pChange)).join(""));

  // OI Spurts — split by OI change % (build-up vs unwind)
  const oiRows=((PAYLOAD.oispurts&&PAYLOAD.oispurts.rows)||[]).filter(r=>r.oiPct!=null);
  const oUp=oiRows.filter(r=>r.oiPct>0).sort((a,b)=>b.oiPct-a.oiPct);
  const oDn=oiRows.filter(r=>r.oiPct<0).sort((a,b)=>a.oiPct-b.oiPct);
  document.getElementById("oi-up-n").textContent=oUp.length;
  document.getElementById("oi-dn-n").textContent=oDn.length;
  const orow=r=>pairRow(r.symbol,[{lab:"Px",v:r.pricePct},{lab:"OI",v:r.oiPct}]);
  fill("oi-gainers", oUp.map(orow).join(""));
  fill("oi-losers",  oDn.map(orow).join(""));

  // countdown (meta refresh performs the reload)
  let secs=PAYLOAD.refreshSecs||300; const cd=document.getElementById("cd");
  cd.textContent=mmss(secs);
  setInterval(()=>{secs=Math.max(0,secs-1); cd.textContent=mmss(secs);},1000);
}
boot();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
