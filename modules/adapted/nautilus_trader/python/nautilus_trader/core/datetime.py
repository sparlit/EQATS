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
UNIX nanosecond timestamp and datetime conversion utilities.
"""


from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from nautilus_trader._libnautilus.core import (
    is_within_last_24_hours,
    last_weekday_nanos,
    micros_to_nanos,
    millis_to_nanos,
    nanos_to_micros,
    nanos_to_millis,
    nanos_to_secs,
    secs_to_millis,
    secs_to_nanos,
    unix_nanos_to_iso8601,
)

if TYPE_CHECKING:
    import pandas as pd


__all__ = [
    "dt_to_unix_nanos",
    "is_within_last_24_hours",
    "last_weekday_nanos",
    "micros_to_nanos",
    "millis_to_nanos",
    "nanos_to_micros",
    "nanos_to_millis",
    "nanos_to_secs",
    "secs_to_millis",
    "secs_to_nanos",
    "unix_nanos_to_dt",
    "unix_nanos_to_iso8601",
]

_NANOS_PER_MICROSECOND = 1_000
_NANOS_PER_SECOND = 1_000_000_000
_SECONDS_PER_DAY = 86_400
_MICROSECOND_PRECISION_DIGITS = 6
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def unix_nanos_to_dt(nanos: int) -> datetime | pd.Timestamp:
    """
    Return the UTC datetime for the given UNIX timestamp in nanoseconds.
    """
    try:
        import pandas as pd
    except ImportError:
        seconds, nanos_remainder = divmod(int(nanos), _NANOS_PER_SECOND)
        microseconds, nanos_remainder = divmod(nanos_remainder, _NANOS_PER_MICROSECOND)
        if nanos_remainder:
            raise ValueError("pandas is required for nanosecond-precision datetimes") from None

        return _UNIX_EPOCH + timedelta(seconds=seconds, microseconds=microseconds)

    return pd.Timestamp(int(nanos), unit="ns", tz="UTC")


def dt_to_unix_nanos(value: int | str | datetime | pd.Timestamp | None) -> int:
    """
    Return the UNIX timestamp in nanoseconds for the given datetime-like value.
    """
    if value is None:
        raise ValueError("value must not be None")

    try:
        import pandas as pd
    except ImportError:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if _has_more_than_microsecond_precision(value):
                raise ValueError("pandas is required for nanosecond-precision datetimes") from None
            value = datetime.fromisoformat(value)
        if isinstance(value, datetime):
            return _datetime_to_unix_nanos(value)
        raise TypeError("value must be datetime-like") from None

    if isinstance(value, pd.Timestamp):
        return int(value.value)

    return int(pd.Timestamp(value).value)


def _has_more_than_microsecond_precision(value: str) -> bool:
    _, separator, remainder = value.partition(".")
    if not separator:
        return False

    digits = 0

    for char in remainder:
        if not char.isdigit():
            break
        digits += 1

    return digits > _MICROSECOND_PRECISION_DIGITS


def _datetime_to_unix_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    delta = value.astimezone(UTC) - _UNIX_EPOCH
    return (
        delta.days * _SECONDS_PER_DAY * _NANOS_PER_SECOND
        + delta.seconds * _NANOS_PER_SECOND
        + delta.microseconds * _NANOS_PER_MICROSECOND
    )
