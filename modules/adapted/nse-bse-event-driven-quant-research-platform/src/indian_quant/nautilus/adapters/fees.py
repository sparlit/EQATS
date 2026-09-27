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


"""India delivery-market fee schedule as a NautilusTrader FeeModel.

Side-aware per-fill commission:
    BUY : brokerage_bps + stamp_buy_bps   (+ flat fee / order)
    SELL: brokerage_bps + stt_sell_bps    (+ flat fee / order)

Defaults reflect typical Indian discount-broker delivery costs. Because the
model plugs into add_venue(fee_model=...), commissions flow automatically
into fills, positions and account reports.
"""


from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.currencies import INR
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.objects import Money


class IndiaDeliveryFeeModel(FeeModel):
    def __init__(
        self,
        *,
        brokerage_bps: float = 3.0,
        stt_sell_bps: float = 100.0,
        stamp_buy_bps: float = 1.5,
        flat_fee_per_order: float = 0.0,
    ) -> None:
        super().__init__()
        self.brokerage_bps = brokerage_bps
        self.stt_sell_bps = stt_sell_bps
        self.stamp_buy_bps = stamp_buy_bps
        self.flat_fee_per_order = flat_fee_per_order

    def get_commission(self, order, fill_qty, fill_px, instrument):  # type: ignore[override]
        qty = float(fill_qty)
        price = float(fill_px)
        notional = qty * price
        if order.side == OrderSide.SELL:
            bps = self.brokerage_bps + self.stt_sell_bps
        else:
            bps = self.brokerage_bps + self.stamp_buy_bps
        total = notional * (bps / 10_000.0) + self.flat_fee_per_order
        return Money(round(total, 2), INR)


__all__ = ["IndiaDeliveryFeeModel"]
