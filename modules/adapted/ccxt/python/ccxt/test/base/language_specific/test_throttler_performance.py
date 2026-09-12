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


import asyncio
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root)

import ccxt.async_support as ccxt


async def test_throttler_performance_helper(exchange, num_requests):
    start_time = exchange.milliseconds()
    tasks = []

    for i in range(num_requests):
        tasks.append(throttle_call(exchange, i, start_time))

    await asyncio.gather(*tasks)

    end_time = exchange.milliseconds()
    return end_time - start_time


async def throttle_call(exchange, index, start_time):
    try:
        # Use the throttler directly without making any API calls
        await exchange.throttle(1)  # cost of 1
        mock_result = {
            "id": "mock",
            "timestamp": exchange.milliseconds(),
            "data": "mock data",
        }
        assert mock_result["id"] == "mock"
        return mock_result
    except Exception as e:
        print(f"Throttle call {index + 1} failed: {e}")
        raise


async def test_throttler():
    exchange1 = ccxt.binance(
        {
            "enableRateLimit": True,
            "rateLimiterAlgorithm": "rollingWindow",
        }
    )

    try:
        rolling_window_time = await test_throttler_performance_helper(exchange1, 100)
    finally:
        await exchange1.close()

    exchange2 = ccxt.binance(
        {
            "enableRateLimit": True,
            "rateLimiterAlgorithm": "leakyBucket",
        }
    )

    try:
        leaky_bucket_time = await test_throttler_performance_helper(exchange2, 20)
    finally:
        await exchange2.close()

    exchange3 = ccxt.binance(
        {
            "enableRateLimit": True,
            "rollingWindowSize": 0.0,
        }
    )

    try:
        rolling_window_0_time = await test_throttler_performance_helper(exchange3, 20)
    finally:
        await exchange3.close()

    rolling_window_time_string = str(round(rolling_window_time, 2))
    leaky_bucket_time_string = str(round(leaky_bucket_time, 2))
    rolling_window_0_time_string = str(round(rolling_window_0_time, 2))  # uses leakyBucket

    assert rolling_window_time <= 1000, (
        "Rolling window throttler should happen immediately, but time was: " + rolling_window_time_string
    )
    assert leaky_bucket_time >= 500, (
        "Leaky bucket throttler should take at least half a second for 20 requests, but time was: "
        + leaky_bucket_time_string
    )
    assert rolling_window_0_time >= 500, (
        "With rollingWindowSize === 0, the Leaky bucket throttler should be used and take at least half a second for 20 requests, time was: "
        + rolling_window_0_time_string
    )

    print("┌───────────────────────────────────────────┬──────────────┬─────────────────┐")
    print("│ Algorithm                                 │ Time (ms)    │ Expected (ms)   │")
    print("├───────────────────────────────────────────┼──────────────┼─────────────────┤")
    print(
        "│ Rolling Window                            │ "
        + rolling_window_time_string.rjust(11)
        + "  │ ~3              │"
    )
    print(
        "│ Leaky Bucket                              │ " + leaky_bucket_time_string.rjust(11) + "  │ ~950            │"
    )
    print(
        "│ Leaky Bucket (rollingWindowSize === 0)    │ "
        + rolling_window_0_time_string.rjust(11)
        + "  │ ~950            │"
    )
    print("└───────────────────────────────────────────┴──────────────┴─────────────────┘")


def test_throttler_performance():
    try:
        # Check if there's already a running event loop
        asyncio.get_running_loop()
        # If we get here, there's already a loop running
        # Create a task and run it (this will be awaited by the caller)
        import concurrent.futures

        # Can't use asyncio.run() in a running loop, so we need to run in thread pool
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, test_throttler())
            future.result()
    except RuntimeError:
        # No event loop is running, safe to use asyncio.run()
        asyncio.run(test_throttler())
