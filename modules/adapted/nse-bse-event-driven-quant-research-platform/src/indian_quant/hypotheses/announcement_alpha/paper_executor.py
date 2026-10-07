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


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from indian_quant.adapters.upstox.execution import UpstoxExecutionClient


class AnnouncementAlphaExecutor:
    """Places paper (sandbox) orders using the platform's UpstoxExecutionClient.

    The sandbox endpoint physically cannot route live orders, so no real
    money is ever at risk.
    """

    def __init__(self, execution_client: UpstoxExecutionClient | None = None):
        self._client = execution_client

    def _get_client(self) -> UpstoxExecutionClient:
        if self._client is not None:
            return self._client
        from indian_quant.adapters.upstox.execution import UpstoxExecutionClient
        from indian_quant.config.settings import UpstoxConfig

        config = UpstoxConfig(sandbox=True)
        self._client = UpstoxExecutionClient(config)
        return self._client

    def place_order(
        self,
        symbol: str,
        exchange: str,
        instrument_key: str,
        quantity: int,
        price: float,
        tag: str = "",
    ) -> dict:
        client = self._get_client()
        from indian_quant.adapters.upstox.execution import (
            OrderSide,
            OrderType,
            ProductType,
            SandboxOrderRequest,
            Validity,
        )

        request = SandboxOrderRequest(
            instrument_key=instrument_key,
            quantity=max(quantity, 1),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            product=ProductType.DELIVERY,
            validity=Validity.DAY,
            limit_price=round(price, 2),
            trigger_price=0.0,
            tag=tag or f"announcement_alpha_{symbol}",
        )
        import asyncio

        report = asyncio.run(client.submit_order(request))
        return {"order_id": report.order_id, "status": report.status, "symbol": symbol}
