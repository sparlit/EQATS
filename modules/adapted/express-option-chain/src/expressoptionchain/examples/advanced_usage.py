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


from expressoptionchain.helper import get_secrets
from expressoptionchain.option_stream import OptionStream
from expressoptionchain.redis_helper import RedisConfig

# the option stream start should be in main module
if __name__ == "__main__":
    secrets = get_secrets()

    symbols = ["NFO:HDFCBANK", "NFO:INFY", "NFO:RELIANCE", "NFO:DRREDDY", "NFO:EICHERMOT"]

    # The percentage criteria filters out options with strike prices that are more than a specified value away
    # from the current spot price. In this example, percentage value is set to 12.5%.
    # By adding this criteria filter, it resolves to 262 tokens instead of 438 tokens if no filter was
    # applied
    criteria = {"name": "percentage", "properties": {"value": 12.5}}

    stream = OptionStream(
        symbols, secrets, expiry="23-02-2023", criteria=criteria, redis_config=RedisConfig(db=1)
    )
    stream.start()
