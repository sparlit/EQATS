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


import datetime

from openchart import NSEData

# Initialize the NSEData class
nse = NSEData()

# Download master data for NSE and NFO
nse.download()

# Define the start and end dates (last 30 days)
end_date = datetime.datetime.now()
start_date = end_date - datetime.timedelta(days=30)

# Fetch 5-minute historical data for RELIANCE
data = nse.historical(
    symbol="RELIANCE", exchange="NSE", start=start_date, end=end_date, interval="5m"
)

# Display the fetched data
if not data.empty:
    print("5-minute historical data for RELIANCE (Last 30 days):")
    print(data)
else:
    print("No data available for RELIANCE for the specified time period.")
