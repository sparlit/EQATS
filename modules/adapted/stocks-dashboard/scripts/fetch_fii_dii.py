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
Fetches daily FII/DII activity (cash segment) and appends it to a committed
history file docs/fii_dii.json, so the FII/DII dashboard accumulates history.

Sources (both free, no key):
  - NiftyTrader  webapi/Resource/fii-dii-activity-data
      ~30 trading days of FII net, DII net and the Nifty 50 close + change%.
      This is the history backfill + ongoing trend, and self-extends each run.
  - NSE          api/fiidiiTradeReact
      Latest provisional day with the full BUY / SELL / NET breakdown for both
      FII/FPI and DII (richer than NiftyTrader's net-only). Needs a cookie warm-up.

Merge is by date (YYYY-MM-DD). NSE's buy/sell/net overrides for the latest day;
NiftyTrader supplies net + Nifty for the rest. Existing history is preserved, so
the series only grows. On total fetch failure the old file is left untouched.

Run:  python -X utf8 fetch_fii_dii.py
"""
import contextlib
import datetime
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "fii_dii.json")  # cash segment (recent + grows)
OUT_MON = os.path.join(ROOT, "docs", "fii_dii_monthly.json")  # monthly aggregates 2014-07 -> today
OUT_FO = os.path.join(ROOT, "docs", "fii_fo.json")  # derivatives net positions (2012 -> today)
OUT_NIFTY = os.path.join(ROOT, "docs", "nifty.json")  # Nifty 50 close history (for chart overlays)
OUT_NIFTY500 = os.path.join(ROOT, "docs", "nifty500.json")  # Nifty 500 close history (backtest calendar-year benchmark)
OUT_BANK = os.path.join(ROOT, "docs", "nifty_bank.json")  # Nifty Bank close history (home-page ticker)
OUT_VIX = os.path.join(ROOT, "docs", "india_vix.json")  # India VIX close history (home-page ticker)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _get(url, headers=None, jar=None, timeout=30, binary=False):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    opener = urllib.request.build_opener()
    if jar is not None:
        opener.add_handler(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(req, timeout=timeout) as r:
        data = r.read()
        return data if binary else data.decode("utf-8", "replace")


def _nse_jar():
    """Warm an NSE cookie jar (the homepage may 403 but still sets the cookie)."""
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    with contextlib.suppress(Exception):
        _get("https://www.nseindia.com/", headers={"User-Agent": UA, "Accept": "text/html"}, jar=jar, timeout=20)
    return jar


def fetch_fo_for_date(dt, jar, include_bs=True):
    """
    Fetch F&O participant data for one date (datetime.date):
      - participant-wise OI (net positions, contracts) for FII/DII/Pro/Client
      - FII derivative buy/sell VALUE (Rs cr) per instrument  [skipped if include_bs=False]
    Returns a compact dict or None if that day's files aren't available.
    The buy/sell .xls only exists for recent dates, so bulk backfill passes include_bs=False.
    """
    import csv
    import io

    ddmmyyyy = dt.strftime("%d%m%Y")
    ddmonyyyy = dt.strftime("%d-%b-%Y")
    hdr = {"User-Agent": UA, "Referer": "https://www.nseindia.com/"}
    fo = {}
    # ---- participant-wise OI (net positions) ----
    try:
        raw = _get(
            f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv",
            headers=hdr,
            jar=jar,
            timeout=25,
        )
        if "Participant" in raw:
            oi = {}
            for row in csv.reader(io.StringIO(raw)):
                if not row or row[0].strip() not in ("Client", "DII", "FII", "Pro"):
                    continue
                v = [int(float(x)) for x in (c.strip() or "0" for c in row[1:15])]
                # cols: 0 FutIdxL 1 FutIdxS 2 FutStkL 3 FutStkS 4 OptIdxCallL 5 OptIdxPutL
                #       6 OptIdxCallS 7 OptIdxPutS 8 OptStkCallL 9 OptStkPutL 10 OptStkCallS
                #       11 OptStkPutS 12 TotLong 13 TotShort
                oi[row[0].strip()] = {"futIdx": [v[0], v[1]], "futStk": [v[2], v[3]], "totL": v[12], "totS": v[13]}
            if oi:
                fo["oi"] = oi
    except Exception:
        pass
    # ---- FII derivative buy/sell value (Rs cr) ----
    if not include_bs:
        return fo or None
    try:
        import xlrd

        blob = _get(
            f"https://nsearchives.nseindia.com/content/fo/fii_stats_{ddmonyyyy}.xls",
            headers=hdr,
            jar=jar,
            timeout=25,
            binary=True,
        )
        wb = xlrd.open_workbook(file_contents=blob)
        sh = wb.sheet_by_index(0)
        want = {
            "INDEX FUTURES": "idxFut",
            "INDEX OPTIONS": "idxOpt",
            "STOCK FUTURES": "stkFut",
            "STOCK OPTIONS": "stkOpt",
        }
        bs = {}
        for r in range(sh.nrows):
            label = str(sh.cell_value(r, 0)).strip().upper()
            if label in want:
                buy = float(sh.cell_value(r, 2) or 0)  # BUY amount (Rs cr)
                sell = float(sh.cell_value(r, 4) or 0)  # SELL amount (Rs cr)
                bs[want[label]] = [round(buy, 2), round(sell, 2)]
        if bs:
            fo["bs"] = bs
    except Exception:
        pass
    return fo or None


def fetch_niftytrader():
    """Return {date: {fiiNet,diiNet,nifty,chg}} or {} on failure."""
    try:
        raw = _get(
            "https://webapi.niftytrader.in/webapi/Resource/fii-dii-activity-data",
            headers={"User-Agent": UA, "Referer": "https://www.niftytrader.in/"},
        )
        rows = json.loads(raw)["resultData"]["fii_dii_data"]
        out = {}
        for r in rows:
            d = r["created_at"][:10]
            out[d] = {
                "fiiNet": r.get("fii_net_value"),
                "diiNet": r.get("dii_net_value"),
                "nifty": r.get("last_trade_price"),
                "chg": r.get("change_per"),
            }
        return out
    except Exception as e:
        print("  ! NiftyTrader fetch failed:", e)
        return {}


def fetch_nse():
    """Return {date: {fiiBuy,fiiSell,fiiNet,diiBuy,diiSell,diiNet}} for the latest day, or {}."""
    try:
        import http.cookiejar

        jar = http.cookiejar.CookieJar()
        h = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
        try:
            _get("https://www.nseindia.com/reports/fii-dii", headers=h, jar=jar, timeout=20)
        except Exception:
            pass  # the cookie still gets set even if the page 403s
        raw = _get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/reports/fii-dii",
            },
            jar=jar,
            timeout=25,
        )
        arr = json.loads(raw)
        out = {}
        for r in arr:
            d = datetime.datetime.strptime(r["date"], "%d-%b-%Y").strftime("%Y-%m-%d")
            rec = out.setdefault(d, {})
            who = "fii" if r["category"].startswith("FII") else "dii"
            rec[who + "Buy"] = float(r["buyValue"])
            rec[who + "Sell"] = float(r["sellValue"])
            rec[who + "Net"] = float(r["netValue"])
        return out
    except Exception as e:
        print("  ! NSE fetch failed:", e)
        return {}


def fetch_monthly_year(year):
    """One calendar year of monthly cash aggregates from NiftyTrader.
    Returns {"YYYY-MM": {fiiNet, diiNet, close(=EOM Nifty), open(=SOM Nifty)}} or {}.
    The endpoint carries history back to 2014-07; empty years return {}.
    """
    try:
        raw = _get(
            "https://webapi.niftytrader.in/webapi/Resource/fii-dii-monthly-aggregate?year=%d" % year,
            headers={"User-Agent": UA, "Referer": "https://www.niftytrader.in/", "Accept": "application/json"},
        )
        ma = (json.loads(raw).get("resultData") or {}).get("monthly_aggregates") or []
        out = {}
        for r in ma:
            yr, mo = r.get("yr"), r.get("mo")
            if not yr or not mo:
                continue
            out["%04d-%02d" % (yr, mo)] = {
                "fiiNet": r.get("fii_net"),
                "diiNet": r.get("dii_net"),
                "close": r.get("nifty_eom_close"),
                "open": r.get("nifty_som_close"),
            }
        return out
    except Exception as e:
        print("  ! monthly %d fetch failed: %s" % (year, e))
        return None  # None = fetch error (keep old); {} = a genuinely empty year


def update_monthly():
    """Rebuild docs/fii_dii_monthly.json — precise monthly FII/DII net + Nifty
    start/end close per month, 2014-07 -> current. Re-fetches every year each run
    so the running (partial) current month and any late restatements stay fresh.
    On a total fetch failure the existing file is left untouched (feed only grows)."""
    try:
        old = {r["ym"]: r for r in json.load(open(OUT_MON, encoding="utf-8")).get("rows", [])}
    except Exception:
        old = {}
    merged = dict(old)
    this_year = datetime.date.today().year
    got_any = False
    for year in range(2014, this_year + 1):
        ym = fetch_monthly_year(year)
        if ym is None:  # fetch error for this year — keep whatever we had
            continue
        got_any = True
        for k, v in ym.items():
            merged[k] = {"ym": k, **v}
        time.sleep(0.25)
    if not got_any:
        print("  ! monthly: all fetches failed — keeping existing untouched")
        return
    rows = [merged[k] for k in sorted(merged)]
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
        open(OUT_MON, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print(
        "  fii_dii_monthly.json: %d months, %s -> %s"
        % (len(rows), rows[0]["ym"] if rows else "-", rows[-1]["ym"] if rows else "-")
    )


def _load_rows(path):
    try:
        return {r["date"]: r for r in json.load(open(path, encoding="utf-8")).get("rows", [])}
    except Exception:
        return {}


def update_cash():
    """Refresh the cash-segment file (recent + grows forward)."""
    hist = _load_rows(OUT)
    # migrate: if old rows carried an embedded 'fo', drop it (now in fii_fo.json)
    for r in hist.values():
        r.pop("fo", None)
    n_before = len(hist)
    nt, nse = fetch_niftytrader(), fetch_nse()
    if not nt and not nse:
        print("  ! cash: both sources failed — keeping existing untouched")
        return list(hist)
    for d, v in nt.items():
        row = hist.setdefault(d, {"date": d})
        for k in ("fiiNet", "diiNet", "nifty", "chg"):
            if v.get(k) is not None:
                row[k] = v[k]
    for d, v in nse.items():
        hist.setdefault(d, {"date": d}).update(v)
    rows = [hist[d] for d in sorted(hist)]
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
        open(OUT, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print(
        "  fii_dii.json (cash): %d rows (was %d), latest %s" % (len(rows), n_before, rows[-1]["date"] if rows else "-")
    )
    return sorted(hist)


def update_fo(cash_dates, max_new=40):
    """Top up the derivatives file with any recent dates missing F&O data."""
    fo = _load_rows(OUT_FO)
    n_before = len(fo)
    missing = [d for d in cash_dates if d not in fo]
    if missing:
        jar = _nse_jar()
        done = 0
        for d in sorted(missing, reverse=True):  # newest first
            if done >= max_new:
                break
            try:
                rec = fetch_fo_for_date(datetime.datetime.strptime(d, "%Y-%m-%d").date(), jar)
                if rec:
                    rec["date"] = d
                    fo[d] = rec
                    done += 1
                time.sleep(0.4)
            except Exception:
                pass
    rows = [fo[d] for d in sorted(fo)]
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
        open(OUT_FO, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print("  fii_fo.json (derivatives): %d rows (was %d)" % (len(rows), n_before))


def update_nifty():
    """Keep docs/nifty.json current by merging the latest Nifty closes from the cash feed
    (historical 2012+ seed is committed once; daily runs just append new days)."""
    try:
        px = json.load(open(OUT_NIFTY, encoding="utf-8")).get("px", {})
    except Exception:
        px = {}
    n0 = len(px)
    for r in _load_rows(OUT).values():
        if r.get("nifty") is not None and r["date"] not in px:
            px[r["date"]] = round(r["nifty"], 2)
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "px": px},
        open(OUT_NIFTY, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print("  nifty.json: %d points (+%d)" % (len(px), len(px) - n0))


def update_yahoo_index(out_path, yahoo_symbol, label):
    """Keep a docs/<index>.json close-history current from a Yahoo index symbol. Merges new
    daily closes; preserves existing history on fetch failure. yahoo_symbol is URL-encoded
    (e.g. '%5ECRSLDX' for ^CRSLDX)."""
    try:
        px = json.load(open(out_path, encoding="utf-8")).get("px", {})
    except Exception:
        px = {}
    n0 = len(px)
    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + yahoo_symbol
            + "?period1=1325376000&period2="
            + str(int(time.time()))
            + "&interval=1d"
        )
        j = json.loads(_get(url, headers={"User-Agent": UA}))
        res = j["chart"]["result"][0]
        for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"], strict=False):
            if c is None:
                continue
            px[time.strftime("%Y-%m-%d", time.gmtime(t))] = round(c, 2)
    except Exception as e:
        print(f"  {label}: fetch failed ({e}) — keeping existing")
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "px": px},
        open(out_path, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print("  %s: %d points (+%d)" % (label, len(px), len(px) - n0))


def main():
    dates = update_cash()
    update_monthly()
    update_fo(dates)
    update_nifty()
    update_yahoo_index(OUT_NIFTY500, "%5ECRSLDX", "nifty500.json")  # ^CRSLDX  — Nifty 500
    update_yahoo_index(OUT_BANK, "%5ENSEBANK", "nifty_bank.json")  # ^NSEBANK — Nifty Bank
    update_yahoo_index(OUT_VIX, "%5EINDIAVIX", "india_vix.json")  # ^INDIAVIX — India VIX


if __name__ == "__main__":
    main()
