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

print("CCXT Version:", ccxt.__version__)

# -----------------------------------------------------------------------------


# Example 1: Transfer between the spot main-account and swap main-account
def main_account_transfer():
    exchange = ccxt.phemex(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            # 'verbose': True,  # for debug output
        }
    )
    code = "USDT"
    amount = 10
    fromAccount = "spot"
    toAccount = "swap"
    params = {}

    try:
        exchange.transfer(code, amount, fromAccount, toAccount, params=params)
    except Exception as err:
        print(err)


# Example 2: Transfer between main-account and sub-account (Requires the main and sub-account UID's found on the account/sub-accounts page on Phemex)
def transfer_between_main_and_sub_accounts():
    exchange = ccxt.phemex(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            # 'verbose': True,  # for debug output
        }
    )
    code = "USDT"
    amount = 10
    fromAccount = "4148428"
    toAccount = "4663243"
    # set the bizType to 'SPOT' or 'PERPETUAL', default is 'SPOT'
    bizType = "PERPETUAL"
    params = {"bizType": bizType}

    try:
        exchange.transfer(code, amount, fromAccount, toAccount, params=params)
    except Exception as err:
        print(err)


# Example 3: Transfer between the spot sub-account and swap sub-account (Requires a sub-account API key and secret)
def sub_account_transfer():
    exchange = ccxt.phemex(
        {
            "apiKey": "YOUR_SUB_ACCOUNT_API_KEY",
            "secret": "YOUR_SUB_ACCOUNT_SECRET",
            # 'verbose': True,  # for debug output
        }
    )
    code = "USDT"
    amount = 10
    fromAccount = "spot"
    toAccount = "swap"
    params = {}

    try:
        exchange.transfer(code, amount, fromAccount, toAccount, params=params)
    except Exception as err:
        print(err)


# Example 4: Use the Implicit API to transfer from swap sub-account to swap main-account
def sub_swap_to_main_swap():
    exchange = ccxt.phemex(
        {
            "apiKey": "YOUR_SUB_ACCOUNT_API_KEY",
            "secret": "YOUR_SUB_ACCOUNT_SECRET",
            # 'verbose': True,  # for debug output
        }
    )
    code = "USDT"
    amount = 10
    convertedAmount = exchange.toEv(amount)

    try:
        exchange.privatePostAssetsFuturesSubAccountsTransfer(
            {
                "amountEv": convertedAmount,
                "currency": code,
            }
        )
    except Exception as e:
        print("privatePostAssetsFuturesSubAccountsTransfer() failed")
        print(e)


main_account_transfer()
# transfer_between_main_and_sub_accounts()
# sub_account_transfer()
# sub_swap_to_main_swap()
