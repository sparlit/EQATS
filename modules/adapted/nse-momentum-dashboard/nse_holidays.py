from __future__ import annotations

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


"""
NSE trading holiday calendar (Capital Market / equity segment).

Source: https://www.nseindia.com/api/holiday-master?type=trading -> data["CM"]

Same access pattern as fno_universe.py: the NSE API rejects bare requests
(needs a browser-like User-Agent plus cookies from hitting the homepage
first), so this warms up a session the same way. Caches the list to disk
(NSE publishes each calendar year's holidays in one batch and rarely
revises it) and falls back to a bundled snapshot if the network or NSE is
unavailable, so nothing that depends on this ever breaks because NSE is
down.

Used to make the scheduled jobs (and the Job Log page's "next run"
display) skip NSE holidays instead of the weekday-only approximation
_is_market_hours() has always documented as a known gap.
"""


import datetime as dt
import json
import os

import requests

CACHE_PATH = os.path.join("cache", "nse_holidays.json")
CACHE_MAX_AGE_DAYS = 30  # NSE publishes the year's list once; no need to
# re-fetch often, unlike the F&O universe which
# actually changes twice a year.

NSE_HOME = "https://www.nseindia.com"
NSE_API = "https://www.nseindia.com/api/holiday-master?type=trading"
SEGMENT = "CM"  # Capital Market -- the equity/cash segment this app trades.

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays",
}

# Bundled snapshot (fetched 2026-08-03, CM segment, calendar year 2026).
# Used only if the live API and the disk cache are both unavailable.
# Refresh with: python nse_holidays.py --refresh
FALLBACK_HOLIDAYS_2026 = [
    "2026-01-15",
    "2026-01-26",
    "2026-02-15",
    "2026-03-03",
    "2026-03-21",
    "2026-03-26",
    "2026-03-31",
    "2026-04-03",
    "2026-04-14",
    "2026-05-01",
    "2026-05-28",
    "2026-06-26",
    "2026-08-15",
    "2026-09-14",
    "2026-10-02",
    "2026-10-20",
    "2026-11-08",
    "2026-11-10",
    "2026-11-24",
    "2026-12-25",
]


def fetch_holidays_live(timeout: int = 15) -> list[str]:
    """Hit the NSE API with a warmed-up session. Returns ISO date strings
    (YYYY-MM-DD) for the CM (equity) segment. Raises on failure."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(NSE_HOME, timeout=timeout)  # sets cookies
    r = s.get(NSE_API, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    rows = payload[SEGMENT]
    return sorted(
        {
            dt.datetime.strptime(row["tradingDate"], "%d-%b-%Y").date().isoformat()
            for row in rows
            if row.get("tradingDate")
        }
    )


def _cache_age_days() -> float:
    if not os.path.exists(CACHE_PATH):
        return 1e9
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(CACHE_PATH))
    return (dt.datetime.now() - mtime).total_seconds() / 86400


def get_holidays(force_refresh: bool = False, verbose: bool = True) -> set[str]:
    """ISO date strings (YYYY-MM-DD) NSE's equity segment is closed on,
    preferring cache, then live API, then bundled fallback."""
    if not force_refresh and _cache_age_days() < CACHE_MAX_AGE_DAYS:
        with open(CACHE_PATH) as f:
            return set(json.load(f)["dates"])

    try:
        dates = fetch_holidays_live()
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump({"fetched": dt.datetime.now().isoformat(), "dates": dates}, f, indent=1)
        if verbose:
            print(f"[nse_holidays] fetched {len(dates)} holidays from NSE")
        return set(dates)
    except Exception as e:
        if verbose:
            print(f"[nse_holidays] live fetch failed ({e})")
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH) as f:
                dates = json.load(f)["dates"]
            if verbose:
                print(f"[nse_holidays] using stale cache ({len(dates)} dates, {_cache_age_days():.0f}d old)")
            return set(dates)
        if verbose:
            print(f"[nse_holidays] using bundled fallback ({len(FALLBACK_HOLIDAYS_2026)} dates)")
        return set(FALLBACK_HOLIDAYS_2026)


def is_trading_holiday(date: dt.date) -> bool:
    return date.isoformat() in get_holidays(verbose=False)


def is_trading_day(date: dt.date) -> bool:
    """Weekday AND not an NSE holiday."""
    return date.weekday() < 5 and not is_trading_holiday(date)


def is_month_start_trading_day(date: dt.date) -> bool:
    """True if `date` is the FIRST trading day of its calendar month --
    same definition backtest.py's rb_dates uses for its monthly rebalance
    schedule (pd.Series(dates).groupby([year, month]).min()), so live's
    "Monthly" cadence option evaluates the sell/keep-zone rule on exactly
    the day the backtest that validated it did, not an approximation."""
    if not is_trading_day(date):
        return False
    d = date - dt.timedelta(days=1)
    while d.month == date.month:
        if is_trading_day(d):
            return False
        d -= dt.timedelta(days=1)
    return True


def is_week_end_trading_day(date: dt.date) -> bool:
    """True if `date` is the LAST trading day of its ISO calendar week --
    same definition backtest.py's rb_dates uses for its weekly rebalance
    schedule (dates restricted to Mon-Fri, grouped by ISO (year, week),
    taking the max), so live's "Weekly" cadence option evaluates the sell/
    keep-zone rule on exactly the day the backtest that validated it did.
    Forward-looking (the opposite shape of is_month_start_trading_day's
    backward walk above) since "last day of the week" requires knowing
    whether any later day in the same ISO week is still a trading day."""
    if not is_trading_day(date):
        return False
    iso_year, iso_week, _ = date.isocalendar()
    d = date + dt.timedelta(days=1)
    while True:
        d_iso_year, d_iso_week, _ = d.isocalendar()
        if (d_iso_year, d_iso_week) != (iso_year, iso_week):
            return True
        if is_trading_day(d):
            return False
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    import sys

    dates = get_holidays(force_refresh="--refresh" in sys.argv)
    print(f"{len(dates)} NSE trading holidays cached")
    for d in sorted(dates):
        print(d)
