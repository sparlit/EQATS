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

# Assuming the structure of test_shared_methods based on common unittest methods

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.append(root)

from ccxt import ExchangeClosedByUser
from ccxt.async_support.base.ws.future import Future


# Helper functions
async def resolve_later(future, result, delay):
    await asyncio.sleep(delay)
    future.resolve(result)


async def cancel_later(future, delay):
    await asyncio.sleep(delay)
    future.cancel()


async def reject_later(future, err, delay):
    await asyncio.sleep(delay)
    future.reject(err)


async def test_resolve_before():
    print("test_resolve")
    future = Future()
    expected_result = "test"
    future.resolve(expected_result)
    assert future.done(), "Future is not marked as done"
    assert future.result() == expected_result, f"Expected result '{expected_result}', got '{future.result()}'"


async def test_reject():
    print("test_reject")
    future = Future()
    test_exception = Exception("test error")
    future.reject(test_exception)
    assert future.done(), "Future is not marked as done"
    try:
        future.result()
        msg = "Expected an exception but none was raised"
        raise AssertionError(msg)
    except Exception as e:
        assert str(e) == "test error", f"Expected 'test error', got '{e!s}'"


async def test_race_success_before():
    print("test_race_success")
    future1 = Future()
    future2 = Future()
    race_future = Future.race([future1, future2])
    future1.resolve("first")
    result = await race_future
    future2.cancel()
    assert result == "first", f"Expected 'first', got '{result}'"


async def test_race_success_after():
    print("test_race_success")
    future1 = Future()
    future2 = Future()
    race_future = Future.race([future1, future2])
    asyncio.create_task(resolve_later(future1, "first", 0.01))
    result = await race_future
    future2.cancel()
    assert result == "first", f"Expected 'first', got '{result}'"


async def test_race_return_first_exception():
    print("test_race_return_first_exception")
    future1 = Future()
    race_future = Future.race([future1])
    future1.reject(Exception("Error in future1"))
    try:
        await race_future
        msg = "Expected an exception but none was raised"
        raise AssertionError(msg)
    except Exception as e:
        assert str(e) == "Error in future1", f"Expected 'Error in future1', got '{e!s}'"


async def test_await_canceled_future():
    print("test_await_canceled_future")
    future = Future()
    try:
        future.cancel()
        await future
        msg = "Expected an exception but none was raised"
        raise AssertionError(msg)
    except asyncio.CancelledError as e:
        assert isinstance(e, asyncio.CancelledError), "Expected asyncio.CancelledError"


async def test_cancel():
    print("test_cancel")
    future = Future()
    asyncio.create_task(cancel_later(future, 0.1))
    try:
        await future
        msg = "Expected an exception but none was raised"
        raise AssertionError(msg)
    except asyncio.CancelledError as e:
        assert isinstance(e, asyncio.CancelledError), "Expected asyncio.CancelledError"


async def test_race_cancel():
    print("test_race_cancel")
    try:
        future1 = Future()
        future2 = Future()
        race_future = Future.race([future1, future2])
        race_future.cancel()
        future1.resolve("success")
        await race_future
        msg = "Expected a cancelledError"
        raise AssertionError(msg)
    except asyncio.CancelledError:
        assert True


async def test_race_mixed_outcomes():
    print("test_race_mixed_outcome")
    future1 = Future()
    future2 = Future()
    race_future = Future.race([future1, future2])
    future1.resolve("first")
    task = asyncio.create_task(reject_later(future2, Exception("Error in future2"), 0.1))
    result = await race_future
    assert result == "first", f"Expected 'first', got '{result}'"
    task.cancel()
    future2.cancel()


async def test_race_with_wait_for_timeout():
    print("test_race_with_wait_for_timeout")
    future1 = Future()

    task = asyncio.create_task(resolve_later(future1, "completed first", 2))

    # Attempt to race the futures with a timeout shorter than their resolution time
    try:
        race_future = Future.race([future1])
        await asyncio.wait_for(race_future, timeout=1)  # Timeout is set deliberately short
        msg = "Expected a timeout but race_future completed"
        raise AssertionError(msg)
    except TimeoutError:
        # Expected outcome, the race_future should not complete within the timeout
        assert True
    await task


async def test_race_with_wait_for_completion():
    print("test_race_with_wait_for_completion")
    future1 = Future()
    future2 = Future()

    task = asyncio.create_task(resolve_later(future1, "completed first", 0.1))

    # Race the futures with a timeout longer than necessary
    try:
        race_future = Future.race([future1, future2])
        result = await asyncio.wait_for(race_future, timeout=1)
        assert result == "completed first", f"Unexpected race result: {result}"
    except TimeoutError:
        msg = "Did not expect a timeout"
        raise AssertionError(msg)
    await task


async def test_race_with_precompleted_future():
    print("test_race_with_precompleted_future")
    future1 = Future()
    future2 = Future()
    future1.resolve("immediate success")
    # Immediately resolved future before race call
    race_future = Future.race([future1, future2])
    result = await race_future
    assert result == "immediate success", "Race did not correctly prioritize already completed future."


async def test_closed_by_user():
    print("test_closed_by_user")
    future1 = Future()
    future2 = Future()
    race_future = Future.race([future1, future2])
    task1 = asyncio.create_task(reject_later(future1, ExchangeClosedByUser(), 0.1))
    task2 = asyncio.create_task(reject_later(future2, ExchangeClosedByUser(), 0.1))
    try:
        await race_future
        msg = "Expected an ExchangeClosedByUser"
        raise AssertionError(msg)
    except ExchangeClosedByUser:
        assert True
        assert task1.done()
        assert task2.done()
    except Exception as e:
        msg = f"Received Exception {e}"
        raise AssertionError(msg)


async def test_race_broadcast_reject_no_unretrieved():
    # a failed handshake broadcast-rejects every raced future in one sweep,
    # the race must swallow the already-done losers or asyncio dumps
    # "Future exception was never retrieved" walls at gc,
    # see https://github.com/ccxt/ccxt/pull/29723
    print("test_race_broadcast_reject_no_unretrieved")
    import gc

    loop = asyncio.get_event_loop()
    complaints = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda l, context: complaints.append(context.get("message", "")))
    try:
        futures = [Future() for i in range(5)]
        raced = Future.race(futures)
        error = ExchangeClosedByUser("broadcast reject")
        for future in futures:
            future.reject(error)
        try:
            await asyncio.wait_for(raced, 1)
            msg = "race should have rejected"
            raise AssertionError(msg)
        except ExchangeClosedByUser:
            pass
        del raced
        del futures
        for _i in range(3):
            gc.collect()
            await asyncio.sleep(0.05)
        unretrieved = [message for message in complaints if "never retrieved" in message]
        assert len(unretrieved) == 0, f"broadcast reject leaked {len(unretrieved)} unretrieved exceptions"
    finally:
        loop.set_exception_handler(previous_handler)


async def test_ws_future():
    await test_resolve_before()
    await test_reject()
    await test_race_success_before()
    await test_race_return_first_exception()
    await test_cancel()
    await test_await_canceled_future()
    await test_race_cancel()
    await test_race_mixed_outcomes()
    await test_race_with_wait_for_timeout()
    await test_race_with_wait_for_completion()
    await test_race_with_precompleted_future()
    await test_closed_by_user()
    await test_race_broadcast_reject_no_unretrieved()
