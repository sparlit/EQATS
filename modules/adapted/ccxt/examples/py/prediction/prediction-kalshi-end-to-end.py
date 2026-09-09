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

# Kalshi prediction end-to-end example (read market data + place/fetch/cancel one order).
#
# Kalshi authenticates with an API Key ID (apiKey) + an RSA private key (privateKey), signing
# each request with RSA-PSS over "{timestamp}{METHOD}{path}". This example targets the demo
# (sandbox) environment via set_sandbox_mode(True).
#
# Usage:
#   KALSHI_APIKEY=... KALSHI_PRIVATEKEY="$(cat key.pem)" \
#   python3 examples/py/prediction/prediction-kalshi-end-to-end.py

import asyncio
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root + "/python")

from ccxt.prediction.kalshi import kalshi  # noqa: E402

MAX_NOTIONAL_USD = 25  # hard cap per trade


async def main():
    api_key = os.environ.get("KALSHI_APIKEY")
    private_key = os.environ.get("KALSHI_PRIVATEKEY")
    if not api_key or not private_key:
        print("Set KALSHI_APIKEY and KALSHI_PRIVATEKEY env vars first.")
        return
    exchange = kalshi({"apiKey": api_key, "privateKey": private_key})
    exchange.set_sandbox_mode(True)  # demo environment
    try:
        await exchange.load_markets()

        # 1) balance (signed GET) -----------------------------------------------------------
        balance = await exchange.fetch_balance()
        print("balance USD:", balance.get("USD"))

        # 2) place a far-below-market limit BUY on the first open outcome, then cancel -------
        # price 0.01 (1 cent) for 1 contract = 0.01 USD notional, far under the cap and the book
        price = 0.01
        size = 1
        notional = price * size
        if notional >= MAX_NOTIONAL_USD:
            print("ABORT: notional >= safety cap")
            return
        placed = None
        outcome = None
        for key in exchange.outcomes:
            if exchange.outcome(key).get("label") != "YES":
                continue
            try:
                placed = await exchange.create_order(key, "limit", "buy", size, price)
                outcome = key
                break
            except Exception as e:
                if "market_closed" in str(e):
                    continue  # market not open for trading right now, try the next one
                raise
        if placed is None:
            print("No open market available to trade right now (all markets closed).")
            return
        print("placed:  id", placed["id"], "| status", placed["status"])
        canceled = await exchange.cancel_order(placed["id"], outcome)
        print("canceled: id", canceled["id"], "| status", canceled["status"])
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
