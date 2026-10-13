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
Implement reconciliation hooks and simulate market order execution.
"""

from types import NotImplementedType
from typing import override

from nautilus_trader import live, model
from nautilus_trader.live.clients import ExecutionClient
from nautilus_trader.model import (
    AccountBalance,
    Currency,
    FillReport,
    LiquiditySide,
    Money,
    OrderSide,
    OrderStatusReport,
    OrderType,
    PositionStatusReport,
    TradeId,
    VenueOrderId,
)

from .constants import NOT_IMPLEMENTED


class TemplateExecutionClient(ExecutionClient):
    """
    Publish deterministic venue data through queued core output.
    """

    async def _connect(self) -> None:
        self.generate_account_state(
            balances=[
                AccountBalance(
                    Money.from_str("100000 USD"),
                    Money.from_str("0 USD"),
                    Money.from_str("100000 USD"),
                ),
                AccountBalance(
                    Money.from_str("0 EUR"),
                    Money.from_str("0 EUR"),
                    Money.from_str("0 EUR"),
                ),
            ],
            margins=[],
            reported=True,
            ts_event=self.clock.timestamp_ns(),
        )

    async def _disconnect(self) -> None:
        pass

    @override
    async def _generate_mass_status(
        self,
        lookback_mins: int | None,
    ) -> model.ExecutionMassStatus | NotImplementedType | None:
        return await super()._generate_mass_status(lookback_mins)

    @override
    async def _generate_order_status_report(
        self,
        command: live.GenerateOrderStatusReport,
    ) -> model.OrderStatusReport | None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _generate_order_status_reports(self, command) -> list[OrderStatusReport]:
        return []

    @override
    async def _generate_fill_reports(self, command) -> list[FillReport]:
        return []

    @override
    async def _generate_position_status_reports(self, command) -> list[PositionStatusReport]:
        return []

    async def _submit_order(self, command) -> None:
        order = command.order
        if order.order_type != OrderType.MARKET:
            self.generate_order_denied(order, "The template executes market orders only")
            return

        quote = self.cache.quote(order.instrument_id)
        if quote is None:
            self.generate_order_denied(order, "No quote is available")
            return

        self.generate_order_submitted(order)

        # Real adapters emit acceptance and fills from venue confirmations.
        # This template simulates both immediately to demonstrate and test the order lifecycle.
        venue_order_id = VenueOrderId(str(order.client_order_id))
        self.generate_order_accepted(order, venue_order_id, self.clock.timestamp_ns())

        price = quote.ask_price if order.side == OrderSide.BUY else quote.bid_price
        self.generate_order_filled(
            order,
            venue_order_id,
            None,
            TradeId(str(order.client_order_id)),
            order.quantity,
            price,
            Currency.from_str("USD"),
            Money.from_str("0.03 USD"),
            LiquiditySide.TAKER,
            self.clock.timestamp_ns(),
        )

    @override
    def _handles_order_venue(self, venue: model.Venue | None) -> bool:
        return super()._handles_order_venue(venue)

    @override
    def _provides_bulk_position_coverage(self, instrument_id: model.InstrumentId) -> bool:
        return super()._provides_bulk_position_coverage(instrument_id)

    @override
    def _calculate_commission(
        self,
        instrument: object,
        last_qty: model.Quantity,
        last_px: model.Price,
        liquidity_side: model.LiquiditySide,
    ) -> model.Money | None:
        return super()._calculate_commission(instrument, last_qty, last_px, liquidity_side)

    @override
    async def _register_external_order(
        self,
        client_order_id: model.ClientOrderId,
        venue_order_id: model.VenueOrderId | None,
        instrument_id: model.InstrumentId,
        strategy_id: model.StrategyId,
        ts_init: int,
    ) -> None:
        return await super()._register_external_order(
            client_order_id,
            venue_order_id,
            instrument_id,
            strategy_id,
            ts_init,
        )

    @override
    async def _on_instrument(self, instrument: object) -> None:
        return await super()._on_instrument(instrument)

    @override
    async def _submit_order_list(self, command: live.SubmitOrderList) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _modify_order(self, command: live.ModifyOrder) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _cancel_order(self, command: live.CancelOrder) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _cancel_all_orders(self, command: live.CancelAllOrders) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _query_account(self, command: live.QueryAccount) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _query_order(self, command: live.QueryOrder) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    @override
    async def _batch_modify_orders(self, command: live.BatchModifyOrders) -> None:
        return await super()._batch_modify_orders(command)

    @override
    async def _batch_cancel_orders(self, command: live.BatchCancelOrders) -> None:
        return await super()._batch_cancel_orders(command)
