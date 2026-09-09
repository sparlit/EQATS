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


"""Diagnose risk check failures."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from src.agents.risk_compliance import RiskLimits, _run_risk_checks

# Simulate a signal like what the system generates
signal = {
    "symbol": "ASIANPAINT",
    "signal_type": "BUY",
    "entry_price": 2775,
    "stop_loss": 2700,
    "target_price": 2900,
    "risk_reward_ratio": 1.66,
    "position_size_pct": 5.0,
    "confidence": 0.8,
    "validation": {"confidence": 0.7},
}

portfolio = {"capital": 1000000, "positions": []}
daily_stats = {"trades_count": 0, "profit_loss": 0, "max_drawdown": 0}
limits = RiskLimits.from_settings()

print("=" * 60)
print("RISK CHECK DIAGNOSIS")
print("=" * 60)
print(f"Current time: {datetime.now().strftime('%H:%M')}")
print(f"Trading hours: {limits.no_trading_before} - {limits.no_trading_after}")
print()

checks = _run_risk_checks(signal, portfolio, daily_stats, limits)

blocking = []
warnings = []

for check in checks:
    status = "PASS" if check.passed else "FAIL"
    if not check.passed:
        if check.severity == "block":
            blocking.append(check)
        else:
            warnings.append(check)
    print(f"[{status}] {check.rule}: {'OK' if check.passed else check.message}")

print()
print("=" * 60)
if blocking:
    print(f"BLOCKING FAILURES: {len(blocking)}")
    for b in blocking:
        print(f"  - {b.rule}: {b.message}")
else:
    print("NO BLOCKING FAILURES - Trade should be approved!")

if warnings:
    print(f"WARNINGS: {len(warnings)}")
print("=" * 60)
