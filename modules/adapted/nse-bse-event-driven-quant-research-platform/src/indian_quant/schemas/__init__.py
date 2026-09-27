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


"""Canonical data contracts for the indian-quant platform.

These models are the single source of truth. Nothing enters the normalized
or validated layers without conforming to one of these contracts.
"""

from indian_quant.schemas.announcement import Announcement
from indian_quant.schemas.corporate_action import CorporateAction
from indian_quant.schemas.enums import (
    AdjustmentStatus,
    CorporateActionType,
    DataSource,
    Exchange,
    OptionType,
    QualityStatus,
    SecurityType,
    Segment,
    SignalName,
    Timeframe,
)
from indian_quant.schemas.events import RegimeLabel, ResearchEvent
from indian_quant.schemas.instrument import (
    InstrumentIdentity,
    OptionInstrument,
    make_instrument_id,
    make_option_local_id,
    parse_instrument_id,
)
from indian_quant.schemas.lineage import Lineage, QualityStamp
from indian_quant.schemas.market_data import MarketBar, OptionQuote, bars_to_frame

__all__ = [
    "AdjustmentStatus",
    "Announcement",
    "CorporateAction",
    "CorporateActionType",
    "DataSource",
    "Exchange",
    "InstrumentIdentity",
    "Lineage",
    "MarketBar",
    "OptionInstrument",
    "OptionQuote",
    "OptionType",
    "QualityStamp",
    "QualityStatus",
    "RegimeLabel",
    "ResearchEvent",
    "SecurityType",
    "Segment",
    "SignalName",
    "Timeframe",
    "bars_to_frame",
    "make_instrument_id",
    "make_option_local_id",
    "parse_instrument_id",
]
