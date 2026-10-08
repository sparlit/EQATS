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
Test runtime behavior.
"""

import asyncio
from decimal import Decimal

import pytest
from nautilus_trader.common import (
    BusMessage,
    Cache,
    Clock,
    ComponentState,
    ComponentTrigger,
    CustomData,
    Environment,
    GreeksCalculator,
    LogColor,
    LogFormat,
    LogLevel,
    MessageBusListener,
    Signal,
    get_exchange_rate,
)
from nautilus_trader.model import DataType, PriceType


@pytest.mark.parametrize(
    ("enum_type", "member", "name"),
    [
        (Environment, Environment.LIVE, "LIVE"),
        (LogColor, LogColor.RED, "RED"),
        (LogLevel, LogLevel.INFO, "INFO"),
    ],
)
def test_common_enums_support_variants_and_from_str(
    enum_type: object,
    member: object,
    name: object,
) -> None:
    """
    Test common enums support variants and from str.
    """
    assert member in list(enum_type.variants())
    assert enum_type.from_str(name) == member


def test_component_state_and_trigger_surface() -> None:
    """
    Test component state and trigger surface.
    """
    assert ComponentState.READY != ComponentState.RUNNING
    assert ComponentTrigger.START != ComponentTrigger.STOP
    assert isinstance(hash(ComponentState.READY), int)
    assert isinstance(hash(ComponentTrigger.START), int)


def test_log_format_surface() -> None:
    """
    Test log format surface.
    """
    assert LogFormat.BOLD == LogFormat.BOLD
    assert LogFormat.BOLD != LogFormat.ENDC
    assert str(LogFormat.BOLD) == "LogFormat.BOLD"


def test_signal_and_custom_data_fields() -> None:
    """
    Test signal and custom data fields.
    """
    signal = Signal("sig", "value", 1, 2)
    custom = CustomData(DataType("X"), [1, 2], 3, 4)

    assert signal.name == "sig"
    assert signal.value == "value"
    assert signal.ts_event == 1
    assert signal.ts_init == 2
    assert custom.data_type.type_name == "X"
    assert custom.value == b"\x01\x02"
    assert custom.ts_event == 3
    assert custom.ts_init == 4


def test_get_exchange_rate_direct_and_inverse_pairs() -> None:
    """
    Test get exchange rate direct and inverse pairs.
    """
    direct = get_exchange_rate(
        "USD",
        "EUR",
        PriceType.MID,
        {"USD/EUR": 0.8},
        {"USD/EUR": 0.8},
    )
    inverse = get_exchange_rate(
        "USD",
        "EUR",
        PriceType.MID,
        {"EUR/USD": 1.25},
        {"EUR/USD": 1.25},
    )

    assert direct == pytest.approx(Decimal("0.8"), abs=Decimal("1e-9"))
    assert inverse == pytest.approx(Decimal("0.8"), abs=Decimal("1e-9"))


def test_message_bus_listener_stream_requires_running_event_loop() -> None:
    """
    Test message bus listener stream requires running event loop.
    """
    listener = MessageBusListener()

    with pytest.raises(RuntimeError, match="running event loop"):
        listener.stream(lambda msg: None)

    listener.close()


def test_message_bus_listener_stream_yields_bus_message() -> None:
    """
    Test message bus listener stream yields bus message.
    """

    async def run_test() -> None:
        """
        Run test.
        """
        listener = MessageBusListener()
        received = []

        listener.stream(received.append)
        listener.publish("topic", b"abc")

        for _ in range(10):
            if received:
                break
            await asyncio.sleep(0.01)

        assert listener.is_active() is True
        assert listener.is_closed() is False
        assert len(received) == 1

        message = received[0]

        assert isinstance(message, BusMessage)
        assert message.topic == "topic"
        assert message.payload == b"abc"

        listener.close()
        await asyncio.sleep(0.1)

        assert listener.is_active() is False
        assert listener.is_closed() is True

    asyncio.run(run_test())


def test_greeks_calculator_construction() -> None:
    """
    Test greeks calculator construction.
    """
    cache = Cache()
    clock = Clock.new_test()
    calc = GreeksCalculator(cache, clock)

    assert isinstance(calc, GreeksCalculator)
