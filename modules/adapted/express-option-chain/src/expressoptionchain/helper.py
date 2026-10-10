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


import json
import os

from expressoptionchain.exceptions import ExpressOptionChainException


def get_time_in_str(dt):
    if not dt:
        return dt
    return dt.strftime("%d-%m-%Y %H:%M:%S")


def get_secrets(filename=f"{os.environ['HOME']}/.kite/secrets"):
    try:
        with open(filename) as f:
            secrets = json.load(f)
            return secrets
    except FileNotFoundError:
        message = f"""{filename} not found. Please put the secrets in {
            filename
        } or execute the the command till
        cat > {filename} << EOF
        {
            "api_key": "your_api_key",
            "api_secret": "your_api_secret",
            "access_token": "generated_access_token"
        }
        EOF
        """
        raise ExpressOptionChainException(message)


def get_hash_value(r, hash_name, key):
    val = r.hget(hash_name, key)
    if val:
        return json.loads(val)
    return val
