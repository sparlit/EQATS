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


"""Canonical enumerations shared across all data contracts."""


from enum import StrEnum


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class Segment(StrEnum):
    EQ = "EQ"
    SME = "SME"
    FO = "FO"
    MF = "MF"
    DEBT = "DEBT"
    IDX = "IDX"
    CURRENCY = "CURRENCY"
    COMMODITY = "COMMODITY"


class SecurityType(StrEnum):
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    ETF = "ETF"
    SGB = "SGB"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    MUTUAL_FUND = "MUTUAL_FUND"
    BOND = "BOND"


class Timeframe(StrEnum):
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"
    DAY = "1d"
    WEEK = "1w"
    MONTH = "1M"

    @property
    def pandas_freq(self) -> str:
        return {
            Timeframe.MIN_1: "1min",
            Timeframe.MIN_5: "5min",
            Timeframe.MIN_15: "15min",
            Timeframe.MIN_30: "30min",
            Timeframe.MIN_60: "60min",
            Timeframe.DAY: "1D",
            Timeframe.WEEK: "W-MON",
            Timeframe.MONTH: "ME",
        }[self]

    @property
    def nautilus_aggregation(self) -> str:
        return {
            Timeframe.MIN_1: "MINUTE",
            Timeframe.MIN_5: "MINUTE",
            Timeframe.MIN_15: "MINUTE",
            Timeframe.MIN_30: "MINUTE",
            Timeframe.MIN_60: "HOUR",
            Timeframe.DAY: "DAY",
            Timeframe.WEEK: "WEEK",
            Timeframe.MONTH: "MONTH",
        }[self]


class CorporateActionType(StrEnum):
    DIVIDEND = "DIVIDEND"
    BONUS = "BONUS"
    SPLIT = "SPLIT"
    RIGHTS = "RIGHTS"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    BUYBACK = "BUYBACK"
    OTHER = "OTHER"


class AdjustmentStatus(StrEnum):
    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    DIVIDEND_ADJUSTED = "DIVIDEND_ADJUSTED"
    FULLY_ADJUSTED = "FULLY_ADJUSTED"
    UNKNOWN = "UNKNOWN"


class QualityStatus(StrEnum):
    RAW = "RAW"
    VALIDATED = "VALIDATED"
    SUSPECT = "SUSPECT"
    REJECTED = "REJECTED"


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"


class DataSource(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    UPSTOX = "UPSTOX"
    MANUAL = "MANUAL"


SCHEMA_VERSION = 1


class SignalName(StrEnum):
    DZ_HI_UP = "dz_hi_up"
    DZ_HI_DN = "dz_hi_dn"
    DZ_LO_UP = "dz_lo_up"
    SPIKE_70 = "spike_70"
    STREAK3 = "streak3"
