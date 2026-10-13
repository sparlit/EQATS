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


import os

from openalgo import api

# Initialize client
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host="http://127.0.0.1:5000",
)

# -------------------------------------------------------
# Get available expiry dates for NIFTY
# -------------------------------------------------------
expiry_result = client.expiry(
    symbol="NIFTY", exchange="NFO", instrumenttype="options", strike_count=10
)

if expiry_result["status"] == "success":
    print("Available NIFTY Expiries:")
    for exp in expiry_result["data"]:
        print(f"  {exp}")
else:
    print("Failed to fetch expiries :", expiry_result.get("message"))

# -------------------------------------------------------
# Get option chain (5 strikes around ATM)
# -------------------------------------------------------
chain = client.optionchain(
    underlying="NIFTY", exchange="NSE_INDEX", expiry_date="30JUN26", strike_count=5
)

print("\nNIFTY Option Chain (5 strikes around ATM):")
print("-" * 50)
print(chain)
print("-" * 50)
print("Strike  | CE LTP (Label) | PE LTP (Label)")

if chain["status"] == "success":
    print(f"\nUnderlying LTP: {chain['underlying_ltp']}")
    print(f"ATM Strike: {chain['atm_strike']}")

    print("\nStrike  | CE LTP (Label) | PE LTP (Label)")
    print("-" * 50)

    for item in chain["chain"]:
        ce = item.get("ce") or {}
        pe = item.get("pe") or {}

        print(
            f"{item['strike']:>7} | "
            f"{ce.get('ltp', '-'):>6} ({ce.get('label', '-'):>4}) | "
            f"{pe.get('ltp', '-'):>6} ({pe.get('label', '-'):>4})"
        )
else:
    print("Failed to fetch option chain :", chain.get("message"))
