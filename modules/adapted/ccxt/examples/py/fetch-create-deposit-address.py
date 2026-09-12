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


# -*- coding: utf-8 -*-

import os
import sys
from pprint import pprint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

# -----------------------------------------------------------------------------
# setup

currency_code = "DASH"  # change me
exchange_id = "poloniex"  # change me

exchange = getattr(ccxt, exchange_id)(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
        # 'verbose': True, // ←- uncomment this for verbose output
        # additional credentials might be required in exchange-specific cases:
        # uid or password for coinbaseexchange, etc...
    }
)

# -----------------------------------------------------------------------------

if not exchange.has["fetchDepositAddress"]:
    print("The exchange does not support fetchDepositAddress() yet")
    sys.exit()

# -----------------------------------------------------------------------------

try:
    print("Trying to fetch deposit address for " + currency_code + " from " + exchange_id + "...")

    fetch_result = exchange.fetch_deposit_address(currency_code)

    print("Successfully fetched deposit address for " + currency_code)

except ccxt.InvalidAddress:
    # never skip proper error handling, whatever it is you're building
    # actually, with crypto error handling should be the largest part of your code

    print("The address for " + currency_code + " does not exist yet")

    if exchange.has["createDepositAddress"]:
        print("Attempting to create a deposit address for " + currency_code + "...")

        try:
            create_result = exchange.create_deposit_address(currency_code)

            # pprint(create_result)  # for debugging

            print(
                "Successfully created a deposit address for " + currency_code + ", fetching the deposit address now..."
            )

            try:
                fetch_result = exchange.fetch_deposit_address(currency_code)

                print("Successfully fetched deposit address for " + currency_code)

            except Exception as e:
                print("Failed to fetch deposit address for " + currency_code, type(e).__name__, str(e))

        except Exception as e:
            print("Failed to create deposit address for " + currency_code, type(e).__name__, str(e))

    else:
        print("The exchange does not support createDepositAddress()")

except Exception as e:
    print("There was an error while fetching deposit address for " + currency_code, type(e).__name__, str(e))
