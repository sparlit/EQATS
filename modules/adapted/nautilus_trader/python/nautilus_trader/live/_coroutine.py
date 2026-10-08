from __future__ import annotations

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


# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Drives Rust-owned adapter operations on the Python event loop.
"""


import asyncio
from contextvars import ContextVar
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


_SUPERVISOR_CANCELLATION = ContextVar("supervisor_cancellation", default=False)


async def drive(operation: _Operation) -> object:
    """
    Pass awaited results and exceptions back to the operation until it completes.
    """
    try:
        await asyncio.sleep(0)
        value: object = None
        error: BaseException | None = None
        while True:
            step = operation.advance(value, error)
            if step[0] is True:
                return step[1]
            try:
                value = await step[1]
                error = None
            except BaseException as e:  # noqa: BLE001 - The operation owns failure and cancellation policy.
                value, error = None, e
    finally:
        operation.close()


class _Operation(Protocol):
    def advance(
        self,
        value: object,
        error: BaseException | None,
    ) -> tuple[Literal[True], object] | tuple[Literal[False], Awaitable[object]]: ...

    def close(self) -> None: ...


def cancel_supervised(task: asyncio.Task[object]) -> bool:
    """
    Keep supervisor origin scoped to this synchronous cancellation chain.
    """
    token = _SUPERVISOR_CANCELLATION.set(True)
    try:
        return task.cancel()
    finally:
        _SUPERVISOR_CANCELLATION.reset(token)


def track_cancellation(task: asyncio.Task[object], request: Callable[[bool], bool]) -> None:
    """
    Suppress repeated supervisor requests, including parent-to-child propagation.
    """
    cancel = task.cancel

    def cancel_tracked(msg: object = None) -> bool:
        if not request(_SUPERVISOR_CANCELLATION.get()):
            return False
        return cancel(msg)

    # asyncio tasks permit instance method overrides; retain the loop-created task
    task.cancel = cancel_tracked  # ty: ignore[invalid-assignment]
