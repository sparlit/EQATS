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


#!/usr/bin/env python
"""Build the §12 15:30-gate intermediates (runbook §12/§88c) so the gate can re-run any time:

  scripts/_trading_days.json  sorted YYYYMMDD ints — union of every symbol's bar dates
  scripts/_me_days.json       last trading day per YYYYMM
  scripts/_gate_events.json   [[sym, annDate], ...] for every annStd/annCon that sits ON a
                              month-end trading day (a monthly-rebalance date)
  scripts/_gate_dates.json    the distinct dates of those events (fetch_filing_times.py input)

Price-calendar source (pick ONE):
  --bin PATH        the master sf_stock_data.bin (CI: the downloaded release asset)
  --parts-dir DIR   a dir holding sf_recent_*.bin / sf_deep_*.bin (local: downloaded live parts)
  --calendar        read the committed scripts/gate_calendar.json instead (no price data needed —
                    the refresh-fundamentals nightly path; refresh-backtest-data keeps it fresh
                    via --calendar-only)

--calendar-only: write ONLY scripts/gate_calendar.json {tdays, me_days} from --bin/--parts-dir
and exit (the daily price workflow's step).

The calendar MUST come from the sf data (it carries weekend special sessions — muhurat Sundays can
be a month's LAST session, e.g. 2016-10-30; a Yahoo-based calendar would miss them and mis-place
month-ends). Fundamentals scanned: docs/sf_fundamentals.json (annStd=idx2, annCon=idx4).
"""
import glob
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
CAL = os.path.join(HERE, "gate_calendar.json")


def bar_dates(paths):
    days = set()
    for p in paths:
        D = json.loads(gzip.decompress(open(p, "rb").read()))
        for o in D.get("data", {}).values():
            days.update(o.get("d") or [])
    return days


def main():
    argv = sys.argv[1:]
    paths = []
    if "--bin" in argv:
        paths = [argv[argv.index("--bin") + 1]]
    elif "--parts-dir" in argv:
        d = argv[argv.index("--parts-dir") + 1]
        paths = sorted(glob.glob(os.path.join(d, "sf_recent_*.bin")) + glob.glob(os.path.join(d, "sf_deep_*.bin")))

    if "--calendar" in argv and not paths:
        cal = json.load(open(CAL))
        tdays, me_days = cal["tdays"], set(cal["me_days"])
    else:
        if not paths:
            sys.exit("need --bin/--parts-dir (or --calendar to use the committed gate_calendar.json)")
        tdays = sorted(bar_dates(paths))
        me = {}
        for d in tdays:
            me[d // 100] = d  # ascending -> last one per month wins
        me_days = set(me.values())
        json.dump({"tdays": tdays, "me_days": sorted(me_days)}, open(CAL, "w"), separators=(",", ":"))
        if "--calendar-only" in argv:
            print(f"gate_calendar.json: {len(tdays)} trading days ({tdays[0]}..{tdays[-1]}), {len(me_days)} month-ends")
            return

    fund = json.load(open(os.path.join(DOCS, "sf_fundamentals.json")))
    events, dates = set(), set()
    for sym, rows in fund.items():
        for r in rows:
            for idx in (2, 4):
                if len(r) > idx and isinstance(r[idx], int) and r[idx] in me_days:
                    events.add((sym, r[idx]))
                    dates.add(r[idx])

    json.dump(tdays, open(os.path.join(HERE, "_trading_days.json"), "w"), separators=(",", ":"))
    json.dump(sorted(me_days), open(os.path.join(HERE, "_me_days.json"), "w"), separators=(",", ":"))
    json.dump(sorted(events), open(os.path.join(HERE, "_gate_events.json"), "w"), separators=(",", ":"))
    json.dump(sorted(dates), open(os.path.join(HERE, "_gate_dates.json"), "w"), separators=(",", ":"))
    print(
        f"trading days {len(tdays)} ({tdays[0]}..{tdays[-1]}), month-ends {len(me_days)}, "
        f"gate events {len(events)} across {len(dates)} distinct dates"
    )


if __name__ == "__main__":
    main()
