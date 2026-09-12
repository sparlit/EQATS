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
"""Bake docs/liquid_universe.json — the turnover universe behind the Season Trends default view.

WHY THIS EXISTS: build_results_season.py runs in refresh-fundamentals.yml (every 30 min), which has
no fresh price bin — only the COMMITTED docs/sf_stock_data.bin, and that one is frozen on purpose
(refresh-market-mood overwrites it in the runner but never commits it; the real bin is ~193 MB, past
GitHub's 100 MB file cap, so it can never be committed fresh). So the season chart was picking its
default universe from a snapshot that stopped advancing on 2026-06-13 while prices ran to 2026-08-07
— 4.8% of the universe wrong (41 newly-liquid names missing, 28 gone-illiquid still counted), drifting
further every day. Downloading the 193 MB release asset 48×/day to fix that is absurd; this sidecar is
~20 KB and rides the once-daily job that already HAS the fresh bin (refresh-backtest-data.yml, right
after the append step).

Out: docs/liquid_universe.json = {asOf, floorCr, window, symbols:[...]}
Run:  python3 -X utf8 scripts/bake_liquid_universe.py          # uses docs/sf_stock_data.bin
      SF_BIN=/tmp/sf_stock_data.bin python3 -X utf8 scripts/bake_liquid_universe.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_results_season import BIN, LIQ, RECENCY_DAYS, TURN_FLOOR_CR, TURN_WINDOW, load_rename, scan_bin_universe


def main():
    src = os.environ.get("SF_BIN") or BIN
    U, end = scan_bin_universe(src, load_rename())
    if not U:
        print(f"REFUSING to write an empty universe (src={src})")
        return 1
    if not end:
        print(f"REFUSING to write a universe with no `end` date (src={src})")
        return 1
    # `recencyDays` is the guarded-bake MARKER as well as a parameter: a sidecar carries no per-symbol
    # dates, so its reader cannot re-screen it — the key's presence is the only way build_liquid_universe()
    # can tell a guarded file from a pre-guard one. Never drop it from this payload.
    json.dump(
        {
            "asOf": end,
            "floorCr": TURN_FLOOR_CR,
            "window": TURN_WINDOW,
            "recencyDays": RECENCY_DAYS,
            "symbols": sorted(U),
        },
        open(LIQ, "w"),
        separators=(",", ":"),
    )
    print("Wrote %s: %d symbols, asOf=%s recencyDays=%d (src=%s)" % (LIQ, len(U), end, RECENCY_DAYS, src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
