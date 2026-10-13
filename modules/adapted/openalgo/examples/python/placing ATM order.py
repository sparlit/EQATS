
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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

print("OpenAlgo Python Bot is running.")

# ------------------------------------------
# Initialize API client
# ------------------------------------------
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host="http://127.0.0.1:5000",
)

# ------------------------------------------
# Fetch NIFTY Spot (must print immediately)
# ------------------------------------------
quote = client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
print("NIFTY QUOTE:", quote)

# ------------------------------------------
# Place NIFTY ATM Option Order - 09DEC25
# ------------------------------------------
response = client.optionsorder(
    strategy="python",
    underlying="NIFTY",  # Underlying Index
    exchange="NSE_INDEX",  # Index exchange
    expiry_date="30JUN26",  # Correct expiry
    offset="OTM2",  # Auto-select ATM strike
    option_type="CE",  # CE or PE
    action="BUY",  # BUY or SELL
    quantity=75,  # 1 Lot = 75
    pricetype="MARKET",  # MARKET or LIMIT
    product="NRML",  # NRML or MIS
    splitsize=0,  # 0 = no split
)

print("ORDER RESPONSE:", response)