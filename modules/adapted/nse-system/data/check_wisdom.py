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


"""Throwaway verification for wisdom.py."""
import json

from traders import wisdom as w

c = w.count()
print(json.dumps(c, indent=2))

assert c["total"] == 76, "expected 76, got " + str(c["total"])
assert c["axioms"] == 5, "expected 5, got " + str(c["axioms"])
assert c["themes"] == 10, "expected 10, got " + str(c["themes"])

# Spot-check the Singhal additions
new_ids = [
    "market_sideways_70pct",
    "confluence_2_3_indicators",
    "never_trade_without_plan",
    "structural_stop_pattern_low",
    "high_vix_skip_trades",
    "first_retracement_only",
    "longer_consolidation_stronger",
    "exit_on_opposite_signal",
    "time_based_exit_intraday",
    "sector_rotation",
    "avoid_overtrading",
    "avoid_analysis_paralysis",
    "trading_journal",
    "start_small",
]
found_ids = {x["id"] for x in w.WISDOM}

for pid in new_ids:
    mark = "OK  " if pid in found_ids else "MISS"
    print(f"  {mark} {pid}")

missing = [p for p in new_ids if p not in found_ids]
assert not missing, "missing: " + ", ".join(missing)
print()
print("ALL CHECKS PASSED")
