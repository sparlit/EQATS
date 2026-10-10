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


"""Regenerate the bundled NSE trading-holiday calendar from the official API.

The application must know the exchange calendar without a network call: an
unreachable or blocked holiday API used to degrade silently into "no holidays",
which turns every holiday into a download that 404s and a date that is retried
on every future run.  This writes ``src/utils/holiday_calendar.py`` from the
same endpoint the application queries at runtime.

    python tools/generate_holiday_calendar.py                # 2013..current+1
    python tools/generate_holiday_calendar.py --first 2013 --last 2027
    python tools/generate_holiday_calendar.py --check        # no write; diff only

The API serves nothing before 2013 -- a request for 2010 answers ``{}`` -- so
that is the floor, not a choice.  Dates below it are handled at download time:
see ``BaseDownloader._settle_absent_reports``.
"""


import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.holiday_manager import HolidayManager  # noqa: E402
from src.utils.http_client import fetch_text_sync  # noqa: E402

TARGET = Path(__file__).resolve().parents[1] / "src" / "utils" / "holiday_calendar.py"

#: The first year the official API answers with a calendar.  Verified by
#: request: 2012 and earlier return an empty object.
API_FIRST_YEAR = 2013

HEADER = '''"""Bundled official NSE capital-market trading holidays.

GENERATED FILE -- do not edit by hand.  Regenerate with:

    python tools/generate_holiday_calendar.py

This exists so the trading calendar survives an unreachable or blocked holiday
API.  Without it a failed refresh silently answers "this year has no holidays",
every holiday is queued as a trading day, its download 404s, and the date is
re-queued on every future run forever.

Source: {source}
Generated: {generated}
Years {first}-{last}; the API serves nothing earlier.
"""


from datetime import date
from typing import Optional


SOURCE = "{source}"
GENERATED_AT = "{generated}"
FIRST_YEAR = {first}
LAST_YEAR = {last}

#: ISO dates per calendar year, exactly as the official API reported them.
HOLIDAYS: dict[int, tuple[str, ...]] = {{
'''

FOOTER = '''}}


_PARSED: dict[int, frozenset] = {{}}


def covered_years() -> frozenset[int]:
    """Years this bundle can answer for without a network call."""

    return frozenset(HOLIDAYS)


def holidays_for_year(year: int) -> Optional[frozenset]:
    """Return the bundled calendar for ``year``, or ``None`` when unknown.

    ``None`` is deliberately different from an empty set: no NSE year has zero
    trading holidays, so "empty" can only mean "not known", and a caller must
    be able to tell those apart.
    """

    if year not in HOLIDAYS:
        return None
    cached = _PARSED.get(year)
    if cached is None:
        cached = frozenset(
            date.fromisoformat(value) for value in HOLIDAYS[year]
        )
        _PARSED[year] = cached
    return cached
'''


def fetch_year(year: int) -> list[str]:
    """Return sorted ISO holiday dates for one year, or raise."""

    url = HolidayManager.SOURCE_TEMPLATE.format(year=year)
    payload = json.loads(fetch_text_sync(url, timeout=20, headers=HolidayManager.SOURCE_HEADERS))
    if not isinstance(payload, dict):
        raise ValueError(f"{year}: response is not an object")
    records = payload.get("CM")
    if not isinstance(records, list) or not records:
        raise ValueError(f"{year}: no CM calendar in the response")
    holidays = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        raw = record.get("tradingDate")
        if not raw:
            continue
        parsed = datetime.strptime(str(raw), "%d-%b-%Y").date()
        if parsed.year == year:
            holidays.add(parsed.isoformat())
    if not holidays:
        raise ValueError(f"{year}: calendar parsed to zero dates")
    return sorted(holidays)


def render(calendar: dict[int, list[str]], generated: str) -> str:
    first, last = min(calendar), max(calendar)
    body = HEADER.format(
        source=HolidayManager.SOURCE_TEMPLATE,
        generated=generated,
        first=first,
        last=last,
    )
    for year in sorted(calendar):
        body += f"    {year}: (\n"
        for value in calendar[year]:
            body += f'        "{value}",\n'
        body += "    ),\n"
    return body + FOOTER.format()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=API_FIRST_YEAR)
    parser.add_argument("--last", type=int, default=date.today().year + 1)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against the committed file without writing it",
    )
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    calendar: dict[int, list[str]] = {}
    for year in range(args.first, args.last + 1):
        try:
            calendar[year] = fetch_year(year)
            print(f"  {year}: {len(calendar[year])} holidays")
        except Exception as error:
            # A year the API does not serve is not an error worth failing on:
            # it is the reason this file exists.
            print(f"  {year}: skipped ({error})")
        time.sleep(args.delay)

    if not calendar:
        print("No year could be fetched; the committed file was left alone.")
        return 1

    rendered = render(calendar, date.today().isoformat())
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        # The generated timestamp always differs, so compare the payload only.
        same = _payload(current) == _payload(rendered)
        print("Bundled calendar is up to date." if same else "DIFFERS from API.")
        return 0 if same else 2

    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Wrote {TARGET} ({len(calendar)} years)")
    return 0


def _payload(text: str) -> str:
    marker = "HOLIDAYS: dict[int, tuple[str, ...]] = {"
    return text[text.find(marker) :] if marker in text else text


if __name__ == "__main__":
    raise SystemExit(main())
