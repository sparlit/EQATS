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


import feedparser
import requests
import yfinance as yf


def main():
    for candidate in ["TMPV.NS", "TMPVL.NS", "TMCV.NS", "TMCVL.NS"]:
        try:
            info = yf.Ticker(candidate).info
            name = info.get("shortName")
            print(f"{candidate}: {'FOUND -> ' + name if name else 'no shortName returned'}")
        except Exception as e:
            print(f"{candidate}: ERROR {e}")

    resp = requests.get(
        "https://www.business-standard.com/rss/markets-106.rss",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    print("\nstatus:", resp.status_code, "bytes:", len(resp.content))
    print(resp.text[:1500])

    parsed = feedparser.parse(resp.text)
    print("\nfeedparser entries found:", len(parsed.entries))
    print("bozo (parse error flag):", parsed.bozo, parsed.get("bozo_exception"))


if __name__ == "__main__":
    main()
