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


"""Fetch market sentiment — VIX, PCR, FII/DII, Max Pain, OI."""

import sys

sys.path.insert(0, "..")

from upstox_data import (
    get_dii_activity,
    get_fii_activity,
    get_market_holidays,
    get_max_pain,
    get_nearest_expiry,
    get_oi,
    get_oi_change,
    get_pcr,
    get_vix,
)

# VIX
vix = get_vix()
print(f"India VIX: {vix}")

# FII / DII
fii = get_fii_activity()
dii = get_dii_activity()
if fii:
    print(
        f"\nFII: Buy {fii['buy_amount']:,.0f} Cr | Sell {fii['sell_amount']:,.0f} Cr | Net {fii['net_amount']:+,.0f} Cr"
    )
if dii:
    print(
        f"DII: Buy {dii['buy_amount']:,.0f} Cr | Sell {dii['sell_amount']:,.0f} Cr | Net {dii['net_amount']:+,.0f} Cr"
    )

# PCR + Max Pain (need expiry)
symbol = "NIFTY"
expiry = get_nearest_expiry(symbol)
if expiry:
    print(f"\n--- {symbol} expiry {expiry} ---")

    pcr = get_pcr(symbol, expiry)
    if pcr:
        print(f"PCR: {pcr['pcr']}")

    mp = get_max_pain(symbol, expiry)
    if mp:
        print(f"Max Pain: {mp['max_pain']}")

    # OI snapshot
    oi = get_oi(symbol, expiry)
    if oi:
        print(f"Total CE OI: {oi['total_calls']:,}")
        print(f"Total PE OI: {oi['total_puts']:,}")

    # OI change (1-day)
    oi_chg = get_oi_change(symbol, expiry)
    if oi_chg:
        print(f"CE OI change: {oi_chg['total_call_change']:+,}")
        print(f"PE OI change: {oi_chg['total_put_change']:+,}")

# Market holidays
print("\n--- Upcoming Holidays ---")
holidays = get_market_holidays()
for h in holidays[:5]:
    print(f"  {h['date']} — {h['description']}")
