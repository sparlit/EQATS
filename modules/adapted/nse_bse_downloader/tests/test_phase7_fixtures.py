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

from tests.fixtures.transport_failures import (
    FAILURE_CASES,
    DeterministicFixtureTransport,
    fixture_response,
)


def test_failure_fixture_matrix_is_deterministic_and_offline():
    first = {case: fixture_response(case) for case in FAILURE_CASES}
    second = {case: fixture_response(case) for case in FAILURE_CASES}
    assert first == second
    assert first["html_200"].status == 200
    assert first["empty_zip"].body.startswith(b"PK")
    assert first["429"].retry_after == "7"
    assert first["403"].status == 403
    assert first["404"].status == 404
    assert first["500"].status == 500


def test_fixture_transport_replays_scripted_attempts_without_network():
    transport = DeterministicFixtureTransport(
        [fixture_response("timeout"), fixture_response("429"), fixture_response("500")]
    )

    async def run():
        errors = []
        for _ in range(3):
            try:
                errors.append(await transport.request())
            except TimeoutError as error:
                errors.append(str(error))
        return errors

    results = asyncio.run(run())
    assert results[0] == "timeout"
    assert results[1].status == 429
    assert results[1].retry_after == "7"
    assert results[2].status == 500
    assert transport.calls == 3
