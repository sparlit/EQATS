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
Load venue instruments for the template data client.
"""

from typing import override

from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import Currency, CurrencyPair, InstrumentId, Price, Quantity, Symbol

from .constants import INSTRUMENT_ID


class TemplateInstrumentProvider(InstrumentProvider):
    """
    Load the deterministic currency pair into local storage.
    """

    @override
    async def load_all_async(self, filters: dict | None = None) -> None:
        """
        Load the template currency pair without network access.
        """
        instrument = CurrencyPair(
            instrument_id=INSTRUMENT_ID,
            raw_symbol=Symbol("EURUSD"),
            base_currency=Currency.from_str("EUR"),
            quote_currency=Currency.from_str("USD"),
            price_precision=5,
            size_precision=0,
            price_increment=Price.from_str("0.00001"),
            size_increment=Quantity.from_str("1"),
            ts_event=11,
            ts_init=13,
        )
        self.add(instrument)

    @override
    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """
        Load requested instruments using the base provider implementation.
        """
        return await super().load_ids_async(instrument_ids, filters)

    @override
    async def load_async(self, instrument_id: InstrumentId, filters: dict | None = None) -> None:
        """
        Load requested instruments using the base provider implementation.
        """
        return await super().load_async(instrument_id, filters)
