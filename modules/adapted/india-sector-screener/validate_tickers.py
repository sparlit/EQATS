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


import concurrent.futures
import datetime
import json
import urllib.parse
import urllib.request

from universe import BENCHMARKS, SECTORS, all_symbols

UA = {"User-Agent": "Mozilla/5.0"}


def probe(root):
    for suf in (".NS", ".BO"):
        s = root + suf
        try:
            req = urllib.request.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}?range=1mo&interval=1d",
                headers=UA,
            )
            r = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
            cl = r["indicators"]["quote"][0]["close"]
            ts = r["timestamp"]
            g = [(t, c) for t, c in zip(ts, cl, strict=False) if c is not None]
            if len(g) >= 8:
                d = datetime.datetime.utcfromtimestamp(g[-1][0]).date()
                if (datetime.date.today() - d).days <= 6:
                    return root, s, "OK", str(d), len(g)
                return root, s, "STALE", str(d), len(g)
        except Exception:
            continue
    return root, "", "FAIL", "", 0


roots = all_symbols()
print("universe size:", len(roots))
bad = []
with concurrent.futures.ThreadPoolExecutor(12) as ex:
    for root, _s, st, d, n in ex.map(probe, roots):
        if st != "OK":
            bad.append((root, st, d, n))
            print("  ", root, st, d, n)
print("problem tickers:", len(bad))
