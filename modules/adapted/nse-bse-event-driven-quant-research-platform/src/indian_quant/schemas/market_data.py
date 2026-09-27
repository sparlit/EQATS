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


"""Market data contracts. Every price record carries explicit semantics."""


from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    import pandas as pd

from indian_quant.schemas.enums import AdjustmentStatus, QualityStatus, Timeframe
from indian_quant.schemas.instrument import InstrumentIdentity
from indian_quant.schemas.lineage import Lineage, QualityStamp


class MarketBar(BaseModel):
    """One OHLCV bar for exactly one canonical instrument and timeframe."""

    model_config = ConfigDict(frozen=True)

    instrument_id: str
    exchange: str
    timestamp: datetime
    timeframe: Timeframe

    open: float
    high: float
    low: float
    close: float

    volume: float = 0.0
    open_interest: float | None = None

    source: str
    source_timestamp: datetime | None = None
    ingestion_timestamp: datetime | None = None
    raw_hash: str | None = None

    adjustment_status: AdjustmentStatus = AdjustmentStatus.UNADJUSTED
    quality_status: QualityStatus = QualityStatus.RAW

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _positive_price(cls, v: float) -> float:
        if v <= 0:
            msg = f"price must be positive, got {v}"
            raise ValueError(msg)
        return v

    @field_validator("volume")
    @classmethod
    def _non_negative_volume(cls, v: float) -> float:
        if v < 0:
            msg = f"volume must be non-negative, got {v}"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _validate_ohlc(self) -> MarketBar:
        if self.high < max(self.open, self.close):
            msg = f"high {self.high} < max(open,close)"
            raise ValueError(msg)
        if self.low > min(self.open, self.close):
            msg = f"low {self.low} > min(open,close)"
            raise ValueError(msg)
        if self.low > self.high:
            msg = f"low {self.low} > high {self.high}"
            raise ValueError(msg)
        return self


class OptionQuote(BaseModel):
    """One option quote snapshot; Greeks live here and nowhere else."""

    model_config = ConfigDict(frozen=True)

    instrument_id: str
    timestamp: datetime

    bid: float | None = None
    ask: float | None = None
    last: float | None = None

    volume: float = 0.0
    open_interest: float | None = None
    implied_volatility: float | None = Field(default=None, ge=0, le=5)

    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    source: str
    source_timestamp: datetime | None = None
    ingestion_timestamp: datetime | None = None
    raw_hash: str | None = None

    @model_validator(mode="after")
    def _validate_spread(self) -> OptionQuote:
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            msg = f"bid {self.bid} > ask {self.ask}"
            raise ValueError(msg)
        return self


def bars_to_frame(bars: list[MarketBar]) -> pd.DataFrame:
    import pandas as pd

    records = [b.model_dump() for b in bars]
    if not records:
        return pd.DataFrame(
            columns=[
                "instrument_id",
                "exchange",
                "timestamp",
                "timeframe",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "open_interest",
                "source",
                "adjustment_status",
                "quality_status",
            ]
        )
    df = pd.DataFrame.from_records(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values(["instrument_id", "timestamp"]).reset_index(drop=True)


__all__ = ["InstrumentIdentity", "Lineage", "MarketBar", "OptionQuote", "QualityStamp", "bars_to_frame"]
