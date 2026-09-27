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


"""Data lineage: every persisted record must answer 'where did this number come from?'."""


from datetime import UTC, datetime

from indian_quant.schemas.enums import SCHEMA_VERSION
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class Lineage(BaseModel):
    source: str
    source_tool: str
    source_request_id: str | None = None
    source_timestamp: datetime | None = None
    ingestion_timestamp: datetime = Field(default_factory=utc_now)
    raw_hash: str | None = None
    schema_version: int = SCHEMA_VERSION


class QualityStamp(BaseModel):
    status: str = "RAW"
    validated_at: datetime | None = None
    validator_version: int = 1
    issues: list[str] = Field(default_factory=list)
