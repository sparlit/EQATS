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
import time

from src.services.pipeline_telemetry import EventLoopLagMonitor, PipelineTelemetry
from src.utils.stage_executor import BoundedStageExecutor


def test_bounded_stage_executor_runs_blocking_work_off_loop_and_records_stages():
    async def run():
        telemetry = PipelineTelemetry()
        executor = BoundedStageExecutor(
            name="prepare", max_workers=1, queue_size=1, telemetry=telemetry
        )
        await executor.start()
        started = time.monotonic()
        results = await asyncio.gather(
            *[executor.run(time.sleep, 0.01, stage="prepare") for _ in range(3)]
        )
        elapsed = time.monotonic() - started
        await executor.close()
        return results, elapsed, telemetry

    results, elapsed, telemetry = asyncio.run(run())
    assert results == [None, None, None]
    assert elapsed >= 0.025
    assert len(telemetry.durations("stage_finished")) == 3
    assert all(
        event.fields["executor"] == "prepare"
        for event in telemetry.events
        if event.kind == "stage_finished"
    )


def test_stage_executor_close_drains_queued_jobs():
    async def run():
        executor = BoundedStageExecutor(name="persist", max_workers=1, queue_size=1)
        first = asyncio.create_task(executor.run(time.sleep, 0.01))
        second = asyncio.create_task(executor.run(time.sleep, 0.01))
        await asyncio.gather(first, second)
        await executor.close()
        return executor._workers

    assert asyncio.run(run()) == []


def test_blocking_stage_work_keeps_event_loop_lag_under_gate():
    async def run():
        telemetry = PipelineTelemetry()
        monitor = EventLoopLagMonitor(telemetry, interval=0.005)
        executor = BoundedStageExecutor(
            name="persist", max_workers=1, queue_size=2, telemetry=telemetry
        )
        await monitor.start()
        await asyncio.gather(*[executor.run(time.sleep, 0.03, stage="persist") for _ in range(4)])
        await monitor.stop()
        await executor.close()
        return sorted(
            event.fields["lag_ms"] for event in telemetry.events if event.kind == "event_loop_lag"
        )

    lags = asyncio.run(run())
    assert lags
    p95 = lags[int(0.95 * (len(lags) - 1))]
    assert p95 < 100
