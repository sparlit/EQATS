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


"""Mapping canonical contracts -> NautilusTrader domain objects.

Verified against nautilus_trader 1.231.0.
"""


from nautilus_trader.model.currencies import INR
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import (
    AggregationSource,
    AssetClass,
    BarAggregation,
    OptionKind,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity, OptionContract
from nautilus_trader.model.objects import Price, Quantity

from indian_quant.schemas.instrument import (
    InstrumentIdentity,
    OptionInstrument,
    to_nautilus_timestamp,
)


def tick_precision(tick_size: float) -> int:
    text = f"{tick_size:.10f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".")[1])


def identity_to_nautilus_equity(identity: InstrumentIdentity) -> Equity:
    precision = tick_precision(identity.tick_size)
    increment = Price(round(identity.tick_size, precision), precision)
    return Equity(
        instrument_id=InstrumentId.from_str(identity.nautilus_instrument_id),
        raw_symbol=Symbol(identity.nautilus_symbol),
        currency=INR,
        price_precision=precision,
        price_increment=increment,
        lot_size=Quantity.from_int(max(1, identity.lot_size)),
        ts_event=to_nautilus_timestamp(_identity_ts(identity)),
        ts_init=to_nautilus_timestamp(_identity_ts(identity)),
        isin=identity.isin,
        info={
            "canonical_instrument_id": identity.instrument_id,
            "segment": identity.segment.value,
            "security_type": identity.security_type.value,
        },
    )


def option_to_nautilus(option: OptionInstrument) -> OptionContract:
    precision = tick_precision(option.tick_size)
    expiration_ns = to_nautilus_timestamp(_datetime_at(option.expiry.year, option.expiry.month, option.expiry.day))
    return OptionContract(
        instrument_id=InstrumentId.from_str(option.nautilus_instrument_id),
        raw_symbol=Symbol(option.nautilus_symbol),
        asset_class=AssetClass.EQUITY_OPTION,
        currency=INR,
        price_precision=precision,
        price_increment=Price(round(option.tick_size, precision), precision),
        multiplier=Quantity.from_int(max(1, option.lot_size)),
        lot_size=Quantity.from_int(max(1, option.lot_size)),
        underlying=option.underlying,
        option_kind=OptionKind.CALL if option.option_type.value == "CE" else OptionKind.PUT,
        strike_price=Price(option.strike, precision),
        activation_ns=0,
        expiration_ns=expiration_ns,
        ts_event=expiration_ns,
        ts_init=expiration_ns,
        info={"canonical_instrument_id": option.instrument_id},
    )


def bar_type_for(identity: InstrumentIdentity, timeframe_value: str = "1d") -> BarType:
    from indian_quant.schemas.enums import Timeframe

    tf = Timeframe(timeframe_value)
    agg_name = tf.nautilus_aggregation
    step = {"MINUTE": 1, "HOUR": 1}.get(agg_name, 1)
    if agg_name == "MINUTE" and tf.value.endswith("m"):
        step = int(tf.value.rstrip("m"))
    spec = BarSpecification(step, BarAggregation[agg_name], PriceType.LAST)
    instrument_id = InstrumentId.from_str(identity.nautilus_instrument_id)
    return BarType(instrument_id, spec, AggregationSource.EXTERNAL)


def market_bar_to_nautilus(bar, bar_type: BarType) -> Bar:
    precision = tick_precision(0.05)
    return Bar(
        bar_type=bar_type,
        open=Price(round(bar.open, precision), precision),
        high=Price(round(bar.high, precision), precision),
        low=Price(round(bar.low, precision), precision),
        close=Price(round(bar.close, precision), precision),
        volume=Quantity.from_str(f"{max(0, int(bar.volume))}"),
        ts_event=int(bar.timestamp.timestamp() * 1_000_000_000),
        ts_init=int(bar.timestamp.timestamp() * 1_000_000_000),
    )


def _identity_ts(identity: InstrumentIdentity):
    from datetime import UTC, datetime

    if identity.expiry:
        return _datetime_at(identity.expiry.year, identity.expiry.month, identity.expiry.day)
    return datetime(1970, 1, 1, tzinfo=UTC)


def _datetime_at(year: int, month: int, day: int):
    from datetime import UTC, datetime

    return datetime(year, month, day, tzinfo=UTC)


__all__ = [
    "bar_type_for",
    "identity_to_nautilus_equity",
    "market_bar_to_nautilus",
    "option_to_nautilus",
    "tick_precision",
]
