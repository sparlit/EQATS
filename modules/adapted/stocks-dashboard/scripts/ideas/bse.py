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


"""Shared BSE fetch helpers for the ideas tool (scripts/ideas/*).

Self-contained on purpose: the daily routine runs on a fresh cloud VM and must not depend on
anything outside this folder except the Python standard library.
All calls go to public BSE endpoints that were verified to work on 2026-09-22:
  - scrip master   : api.bseindia.com/BseIndiaAPI/api/ListofScripData/w  (mcap in Rs crore)
  - daily bhavcopy : www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV
  - announcements  : api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w (50 rows/page)
  - price history  : api.bseindia.com/BseIndiaAPI/api/StockPriceCSVDownload/w
  - corp actions   : api.bseindia.com/BseIndiaAPI/api/CorporateAction/w
  - attachment     : www.bseindia.com/xml-data/corpfiling/AttachLive/<ATTACHMENTNAME>

The two hosts fail independently: BSE's Akamai edge can refuse api.bseindia.com outright for a
whole network while www.bseindia.com keeps serving (measured 2026-09-23/24, runbook 144e). Anything
that can be answered from the bhavcopy therefore has a www-only fallback - see bhav_history().
"""
import csv
import datetime
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ist

# Honest identification, same set as scripts/bse_headers.py (no browser impersonation; runbook §181).
UA = "stocks-dashboard-research/1.0"
HDR = {
    "User-Agent": UA,
    "Referer": "https://www.bseindia.com/",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json, text/plain, */*",
}
CACHE = os.environ.get("IDEAS_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache"))
os.makedirs(CACHE, exist_ok=True)


def _get(url, timeout=60, retries=3, sleep=0.6):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout) as f:
                data = f.read()
            time.sleep(sleep)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:  # terminal for this URL - retrying just burns 6s of sleeps
                msg = f"GET failed {url}: {e}"
                raise RuntimeError(msg)
            last = e
            time.sleep(2 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    msg = f"GET failed {url}: {last}"
    raise RuntimeError(msg)


def get_attachment(url, timeout=120):
    """Fetch a corpfiling attachment, following BSE's Live -> His move.

    BSE serves a filing's PDF under /AttachLive/ when it is fresh and moves it to /AttachHis/
    later, keeping the same uuid. The announcement feed keeps handing out the AttachLive link
    after the move, so that link 404s. Whichever form we are given, try the other one before
    giving up (2026-09-22: every Modison PDF 404'd on AttachLive and resolved on AttachHis,
    which is why its dossier extracted 0 documents).
    """
    alt = (
        url.replace("/AttachLive/", "/AttachHis/")
        if "/AttachLive/" in url
        else url.replace("/AttachHis/", "/AttachLive/")
        if "/AttachHis/" in url
        else None
    )
    try:
        return _get(url, timeout=timeout)
    except Exception:
        if not alt:
            raise
    return _get(alt, timeout=timeout)


def scrip_master():
    """All active BSE equity scrips with market cap (Rs crore). Cached for the day."""
    fn = os.path.join(CACHE, f"master_{ist.today():%Y%m%d}.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    data = _get(
        "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
    )
    rows = json.loads(data)
    json.dump(rows, open(fn, "w"))
    return rows


def bhavcopy(d):
    """BSE equity bhavcopy for date d (datetime.date) -> list of dict rows, or None if not published.
    Rows: scrip (str), isin, symbol, series, name, open, high, low, close, prev_close, volume, turnover, trades."""
    fn = os.path.join(CACHE, f"bhav_{d:%Y%m%d}.csv")
    if not os.path.exists(fn):
        if d.weekday() >= 5:
            return None
        url = f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV"
        try:
            data = _get(url, sleep=0.3)
        except Exception:
            return None
        if len(data) < 100000 or not data.startswith(b"TradDt"):
            # holiday / not yet published: BSE returns a small HTML stub
            return None
        open(fn, "wb").write(data)
    out = []
    for r in csv.DictReader(open(fn, encoding="utf-8", errors="ignore")):
        if r.get("FinInstrmTp") != "STK":
            continue
        try:
            out.append(
                {
                    "scrip": r["FinInstrmId"].strip(),
                    "isin": r["ISIN"].strip(),
                    "symbol": r["TckrSymb"].strip(),
                    "series": r["SctySrs"].strip(),
                    "name": r["FinInstrmNm"].strip(),
                    "open": float(r["OpnPric"] or 0),
                    "high": float(r["HghPric"] or 0),
                    "low": float(r["LwPric"] or 0),
                    "close": float(r["ClsPric"] or 0),
                    "prev_close": float(r["PrvsClsgPric"] or 0),
                    "volume": float(r["TtlTradgVol"] or 0),
                    "turnover": float(r["TtlTrfVal"] or 0),
                    "trades": int(float(r["TtlNbOfTxsExctd"] or 0)),
                }
            )
        except Exception:
            continue
    return out


def nse_bhavcopy(d):
    """NSE cash-market UDiFF bhavcopy for date d -> list of dict rows (same shape as bhavcopy()), or None.

    Used to price ideas on names listed only on NSE (NSE Emerge SME), which BSE's files never carry.
    Same UDiFF columns as BSE's file; every series is kept (EQ, BE, SM, ST ...). Honest headers as above.
    """
    fn = os.path.join(CACHE, f"nse_bhav_{d:%Y%m%d}.csv")
    if not os.path.exists(fn):
        if d.weekday() >= 5:
            return None
        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
            with urllib.request.urlopen(req, timeout=60) as f:
                data = f.read()
            time.sleep(0.3)
        except Exception:
            return None  # 404 on holidays / not yet published; a network refusal also lands here
        import zipfile

        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            raw = z.read(z.namelist()[0])
        except Exception:
            return None
        if not raw.startswith(b"TradDt"):
            return None
        open(fn, "wb").write(raw)
    out = []
    for r in csv.DictReader(open(fn, encoding="utf-8", errors="ignore")):
        if r.get("FinInstrmTp") != "STK":
            continue
        try:
            out.append(
                {
                    "symbol": r["TckrSymb"].strip(),
                    "isin": r["ISIN"].strip(),
                    "series": r["SctySrs"].strip(),
                    "open": float(r["OpnPric"] or 0),
                    "high": float(r["HghPric"] or 0),
                    "low": float(r["LwPric"] or 0),
                    "close": float(r["ClsPric"] or 0),
                    "prev_close": float(r["PrvsClsgPric"] or 0),
                    "volume": float(r["TtlTradgVol"] or 0),
                }
            )
        except Exception:
            continue
    return out


def nse_bhav_history(symbols, d_from, d_to=None, max_days=800):
    """Close history for NSE symbols from the daily NSE bhavcopies: {symbol: [dict(date, ...)]} oldest first.
    A missing day is absent, never zero-filled."""
    want = {str(s).strip().upper() for s in symbols}
    d_to = d_to or ist.today()
    out = {s: [] for s in want}
    d, days = d_from, 0
    while d <= d_to and days < max_days:
        days += 1
        cur = d
        d += datetime.timedelta(days=1)
        rows = nse_bhavcopy(cur)
        if not rows:
            continue
        for r in rows:
            if r["symbol"] in want and r["close"]:
                out[r["symbol"]].append(
                    {
                        "date": cur,
                        "open": r["open"],
                        "high": r["high"],
                        "low": r["low"],
                        "close": r["close"],
                        "volume": r["volume"],
                    }
                )
    for s in out:
        out[s].sort(key=lambda r: r["date"])
    return out


def trading_days_back(n, end=None):
    """Return the last n dates for which a bhavcopy exists, newest first (walks back over holidays)."""
    d = end or ist.today()
    out = []
    tries = 0
    while len(out) < n and tries < n * 3 + 15:
        if bhavcopy(d):
            out.append(d)
        d -= datetime.timedelta(days=1)
        tries += 1
    return out


def bhav_history(scrips, d_from, d_to=None, max_days=800):
    """Close history for a set of scrip codes, assembled from the daily bhavcopies.

    A fallback for price_history(). The per-scrip endpoint lives on api.bseindia.com, which BSE's
    Akamai edge refuses outright from some networks (measured 2026-09-23 20:07 IST -> 2026-09-24
    20:00 IST: every api call 403 while www.bseindia.com, which serves the bhavcopy, answered 200).
    The bhavcopy carries the same closes, so a scorecard need not go blind when the api does.

    One pass over the dates fills every scrip at once, so the cost is the same for one idea or twenty.
    Returns {scrip: [dict(date, open, high, low, close, volume), ...]} oldest first, and only the
    dates whose bhavcopy actually downloaded - a missing day is absent, never zero-filled.
    """
    want = {str(s).strip() for s in scrips}
    d_to = d_to or ist.today()
    out = {s: [] for s in want}
    d, days = d_from, 0
    while d <= d_to and days < max_days:
        days += 1
        rows = bhavcopy(d)
        d += datetime.timedelta(days=1)
        if not rows:
            continue
        cur = d - datetime.timedelta(days=1)
        for r in rows:
            if r["scrip"] in want:
                out[r["scrip"]].append(
                    {
                        "date": cur,
                        "open": r["open"],
                        "high": r["high"],
                        "low": r["low"],
                        "close": r["close"],
                        "volume": r["volume"],
                    }
                )
    for s in out:
        out[s].sort(key=lambda r: r["date"])
    return out


# Set by announcements() on every call: True when a page failed and the list came back short, so a
# caller can tell "the feed was blocked" from "a quiet day". Both look like zero rows otherwise.
last_announcements_partial = False


def announcements(d_from, d_to=None, max_pages=40):
    """All BSE announcements between two dates (inclusive), as the API rows (paginated, 50/page)."""
    global last_announcements_partial
    last_announcements_partial = False
    d_to = d_to or d_from
    fn = os.path.join(CACHE, f"ann_{d_from:%Y%m%d}_{d_to:%Y%m%d}.json")
    if os.path.exists(fn) and d_to < ist.today():
        return json.load(open(fn))
    rows = []
    partial = False
    for p in range(1, max_pages + 1):
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1&strPrevDate=%s"
            "&strScrip=&strSearch=P&strToDate=%s&strType=C&subcategory=-1"
            % (p, d_from.strftime("%Y%m%d"), d_to.strftime("%Y%m%d"))
        )
        try:
            t = json.loads(_get(url, sleep=0.4)).get("Table") or []
        except Exception as e:
            # One failed page used to end the loop quietly and then CACHE the short list, so a
            # transient error became a permanently thin announcement set for that date, with nothing
            # to distinguish it from a genuinely quiet day. Say so, and never cache a partial fetch.
            print(
                f"announcements {d_from}..{d_to}: page {p} failed ({e}); returning {len(rows)} rows "
                "from the pages that did load, NOT caching this partial fetch"
            )
            partial = True
            last_announcements_partial = True
            break
        rows += t
        if len(t) < 50:
            break
    if not partial:
        json.dump(rows, open(fn, "w"))
    return rows


def attachment_url(row):
    a = (row.get("ATTACHMENTNAME") or "").strip()
    return f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{a}" if a else ""


def price_history(scrip, d_from=None, d_to=None):
    """Daily OHLC history for a scrip code from BSE (unadjusted). List of dict rows oldest first."""
    d_from = d_from or datetime.date(2021, 1, 1)
    d_to = d_to or ist.today()
    url = "https://api.bseindia.com/BseIndiaAPI/api/StockPriceCSVDownload/w?pageType=0&rbType=D&Scode={}&FDates={}&TDates={}".format(
        scrip, d_from.strftime("%d/%m/%Y"), d_to.strftime("%d/%m/%Y")
    )
    data = _get(url).decode("utf-8", "ignore")
    out = []
    for r in csv.DictReader(io.StringIO(data)):
        try:
            d = datetime.datetime.strptime(r["Date"].strip(), "%d-%B-%Y").date()
            out.append(
                {
                    "date": d,
                    "open": float(r["Open Price"]),
                    "high": float(r["High Price"]),
                    "low": float(r["Low Price"]),
                    "close": float(r["Close Price"]),
                    "volume": float(r["No.of Shares"] or 0),
                }
            )
        except Exception:
            continue
    out.sort(key=lambda r: r["date"])
    return out


def corporate_actions(scrip):
    """Bonus/split events -> list of (ex_date, factor, label). Factor >1 divides prices before ex_date."""
    import re

    try:
        ca = json.loads(_get(f"https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w?scripcode={scrip}"))
    except Exception:
        return []
    ev, seen = [], set()

    def pd(s):
        for f in ("%d %b %Y", "%d-%B-%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime((s or "").strip(), f).date()
            except Exception:
                pass
        return None

    for e in ca.get("Table2") or []:
        c2 = (e.get("purpose_code") or "").strip()
        p = e.get("purpose") or ""
        ex = pd(e.get("Ex_date"))
        if not ex:
            continue
        f = None
        if c2 == "BN" or "bonus" in p.lower():
            mm = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", p)
            if mm:
                a, b = float(mm.group(1)), float(mm.group(2))
                f = (a + b) / b
        elif c2 == "SS" or "split" in p.lower():
            mm = re.findall(r"Rs\.?\s*(\d+(?:\.\d+)?)", p)
            if len(mm) >= 2:
                f = float(mm[0]) / float(mm[1])
        if f and f > 1 and (ex, round(f, 4)) not in seen:
            seen.add((ex, round(f, 4)))
            ev.append((ex, f, p.strip()))
    for e in ca.get("Table1") or []:
        if "bonus" not in (e.get("XTYPE") or "").lower():
            continue
        ex = pd(e.get("BCRD_FROM"))
        val = e.get("VALUE") or ""
        mm = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", val)
        if not ex or not mm:
            continue
        a, b = float(mm.group(1)), float(mm.group(2))
        f = (a + b) / b
        if any(abs((ex - x[0]).days) <= 5 for x in ev):
            continue
        ev.append((ex, f, "Bonus " + val))
    return sorted(ev)


def apply_adjustments(rows, events):
    """Back-adjust `rows` in place for `events`, adding any unrecorded one-day gap that matches a
    standard bonus/split factor. Shared by adjusted_history() and the bhavcopy fallback so the two
    can never drift apart on what counts as a split."""
    if not rows:
        return rows, list(events)
    events = list(events)
    STD = [1.1, 1.2, 1.25, 1.333, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 11, 20]
    for i in range(1, len(rows)):
        a, b = rows[i - 1]["close"], rows[i]["close"]
        if a <= 0 or b <= 0:
            continue
        ratio = a / b
        if ratio < 1.3:
            continue
        if any(abs((rows[i]["date"] - ex).days) <= 5 for ex, _, _ in events):
            continue
        near = min(STD, key=lambda f: abs(f - ratio) / f)
        if abs(near - ratio) / near <= 0.06:
            events.append((rows[i]["date"], near, f"unrecorded gap x{ratio:.2f}"))
    events.sort()
    for ex, f, _ in events:
        for r in rows:
            if r["date"] < ex:
                for k in ("open", "high", "low", "close"):
                    if r.get(k):
                        r[k] = r[k] / f
    return rows, events


def adjusted_history(scrip, d_from=None):
    """Price history back-adjusted for bonus/split (recorded + unrecorded one-day gaps matching a standard factor)."""
    rows = price_history(scrip, d_from)
    if not rows:
        return rows, []
    return apply_adjustments(rows, corporate_actions(scrip))
