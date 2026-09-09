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


# Prediction markets example (async-only)
#
# Prediction-market exchanges live under ccxt.prediction and extend
# PredictionExchange, which adds events/outcomes helpers on top of Exchange.

import asyncio
import os
import sys

# use this repo's python/ (which has ccxt.prediction) rather than a pip-installed ccxt
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "python"
    ),
)
import ccxt.prediction  # noqa: E402


async def main():
    exchange = ccxt.prediction.polymarket()
    print("id:", exchange.id)
    print("isPrediction:", exchange.isPrediction())
    try:
        events = await exchange.fetch_events({"query": "Fed Chair"})
        print("fetchEvents({query}):", len(events))
        markets = await exchange.fetch_markets({"query": "Fed"})
        print("fetched markets:", len(markets))
    except Exception as e:
        print("fetchMarkets skipped (offline/geo):", type(e).__name__)
    finally:
        # close(True) also tears down the aiohttp REST session/connector; a bare close() only
        # closes WS clients, so aiohttp warns about the still-open REST connector (base ccxt behaviour)
        await exchange.close(True)


asyncio.run(main())
