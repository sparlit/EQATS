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
Test configs behavior.
"""

from nautilus_trader.infrastructure import PostgresCacheConfig, RedisCacheConfig


def test_redis_cache_config_defaults() -> None:
    """
    Test redis cache config defaults.
    """
    config = RedisCacheConfig()

    assert config.host is None
    assert config.port is None
    assert config.username is None
    assert config.password is None
    assert config.ssl is False
    assert config.connection_timeout == 20
    assert config.response_timeout == 20
    assert config.number_of_retries == 100
    assert config.exponent_base == 2
    assert config.max_delay == 1000
    assert config.factor == 2


def test_redis_cache_config_accepts_explicit_kwargs() -> None:
    """
    Test redis cache config accepts explicit kwargs.
    """
    config = RedisCacheConfig(
        host="redis.example.com",
        port=6380,
        username="user",
        password="secret",
        ssl=True,
        connection_timeout=7,
        response_timeout=8,
        number_of_retries=9,
        exponent_base=3,
        max_delay=10,
        factor=4,
    )

    assert config.host == "redis.example.com"
    assert config.port == 6380
    assert config.username == "user"
    assert config.password == "secret"
    assert config.ssl is True
    assert config.connection_timeout == 7
    assert config.response_timeout == 8
    assert config.number_of_retries == 9
    assert config.exponent_base == 3
    assert config.max_delay == 10
    assert config.factor == 4


def test_postgres_cache_config_defaults() -> None:
    """
    Test postgres cache config defaults.
    """
    config = PostgresCacheConfig()

    assert config.host is None
    assert config.port is None
    assert config.username is None
    assert config.password is None
    assert config.database is None


def test_postgres_cache_config_accepts_explicit_kwargs() -> None:
    """
    Test postgres cache config accepts explicit kwargs.
    """
    config = PostgresCacheConfig(
        host="postgres.example.com",
        port=5433,
        username="user",
        password="secret",
        database="nautilus",
    )

    assert config.host == "postgres.example.com"
    assert config.port == 5433
    assert config.username == "user"
    assert config.password == "secret"
    assert config.database == "nautilus"
