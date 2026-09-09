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


"""Report whether the multi-horizon shadow can be presented for human promotion review."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from old_nse_hull.multi_horizon.readiness import assess


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow-state", default="old_nse_hull_shadow_state.json")
    parser.add_argument("--walkforward", default="output/old_nse_hull_walkforward.json")
    parser.add_argument("--historical-state", default="old_nse_hull_historical_replay_state.json")
    args = parser.parse_args()
    result = assess(args.shadow_state, args.walkforward, args.historical_state)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
