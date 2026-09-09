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


"""Refuse to publish a bad dataset.

Run after screener.py. Exits non-zero with an explanation if data.json looks
wrong, so an automated refresh fails loudly instead of quietly replacing a good
page with a broken one.
"""

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_UNIVERSE = 240  # normally ~278
MAX_AGE_DAYS = 9  # a Saturday run sees a Friday close; allow for holidays

with open(os.path.join(HERE, "data.json"), encoding="utf-8") as fh:
    d = json.load(fh)

problems = []

end = dt.date.fromisoformat(d["week_end"])
base = dt.date.fromisoformat(d["baseline"])
age = (dt.date.today() - end).days

if age > MAX_AGE_DAYS:
    problems.append(
        f"week_end {end} is {age} days old (limit {MAX_AGE_DAYS}). "
        "Either the market has been shut, or the price source stopped updating."
    )
if not 3 <= (end - base).days <= 12:
    problems.append(
        f"baseline {base} is {(end - base).days} days before week_end {end}; "
        "expected about 7. The week-over-week comparison may be wrong."
    )
if d["universe_size"] < MIN_UNIVERSE:
    problems.append(
        f"only {d['universe_size']} stocks resolved (expected >= {MIN_UNIVERSE}). "
        f"Unresolved: {', '.join(d['unresolved']) or 'none'}. "
        "Tickers most likely changed - run validate_tickers.py."
    )
if len(d["sectors"]) < 18:
    problems.append(f"only {len(d['sectors'])} sectors built (expected 21).")
if not d.get("benchmarks"):
    problems.append("no benchmark indices resolved.")

if problems:
    print("Output failed its sanity checks - NOT publishing:\n", file=sys.stderr)
    for p in problems:
        print(f"  * {p}", file=sys.stderr)
    sys.exit(1)

print(
    f"OK: week {d['week_start']} -> {d['week_end']} (baseline {d['baseline']}), "
    f"{d['universe_size']} stocks, {len(d['sectors'])} sectors, "
    f"{len(d['benchmarks'])} benchmarks, {age}d old"
)
