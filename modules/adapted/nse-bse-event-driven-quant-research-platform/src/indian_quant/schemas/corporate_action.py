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


"""Corporate action contract. Completely separate from price data."""


from datetime import date, datetime
from typing import Any

from indian_quant.schemas.enums import CorporateActionType
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CorporateAction(BaseModel):
    """A corporate action event keyed to a canonical instrument."""

    model_config = ConfigDict(frozen=True)

    instrument_id: str
    isin: str | None = None

    action_type: CorporateActionType
    announcement_date: date | None = None
    record_date: date | None = None
    ex_date: date | None = None
    effective_date: date | None = None

    ratio: float | None = None
    old_value: float | None = None
    new_value: float | None = None
    amount: float | None = None

    source: str
    source_id: str | None = None
    document_url: str | None = None
    source_timestamp: datetime | None = None
    ingestion_timestamp: datetime | None = None
    raw_payload_hash: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_action(self) -> CorporateAction:
        if self.action_type == CorporateActionType.DIVIDEND and self.amount is None:
            msg = "DIVIDEND requires amount"
            raise ValueError(msg)
        if (
            self.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS)
            and self.ratio is None
            and not (self.old_value and self.new_value)
        ):
            msg = f"{self.action_type} requires ratio or old_value/new_value"
            raise ValueError(msg)
        return self

    def adjustment_ratio(self) -> float:
        """Multiplicative factor applied to pre-ex-date prices (back-adjustment).

        A 10->2 split means one old share became five, so historical prices
        are multiplied by new/old = 0.2. A 1:1 bonus halves pre-ex prices.
        """
        if self.action_type == CorporateActionType.SPLIT:
            if self.old_value and self.new_value:
                return self.new_value / self.old_value
            if self.ratio:
                return 1.0 / self.ratio
            return 1.0
        if self.action_type == CorporateActionType.BONUS:
            if self.ratio:
                parts = str(self.ratio).split(":")
                if len(parts) == 2:
                    bonus, held = float(parts[0]), float(parts[1])
                    return held / (held + bonus)
                return 1.0 / (1.0 + self.ratio)
            return 1.0
        return 1.0
