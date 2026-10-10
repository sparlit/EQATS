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


from expressoptionchain.option_chain import OptionChainFetcher

option_chain_fetcher = OptionChainFetcher()

# option chain for each trading symbol can be fetched in 3 ms
option_chain = option_chain_fetcher.get_option_chain("NFO:HDFCBANK")

while True:
    option_chains = option_chain_fetcher.get_option_chains(
        ["NFO:HDFCBANK", "NFO:INFY", "NFO:RELIANCE", "NFO:DRREDDY", "NFO:EICHERMOT"]
    )
    # do some processing on option chains
    break
