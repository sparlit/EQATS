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


"""BSE bhavcopy ingestion via the bseindia Python library.

BSE's CDN blocks datacenter IPs (serves HTML block page with HTTP 200).
The bseindia library bypasses this by using BSE's internal API endpoints.

Series mapping (BSE uses different series codes than NSE):
    B  -> EQ  (BSE equity)
    A  -> EQ  (A Group)
    X  -> EQ  (Extra)
    XT -> EQ  (Extra Trading)
    MT -> SME (Modified Trading / SME)
    M  -> SME (Main Board SME)
    T  -> SME (Trading)

Sources:
    bseindia lib: equity.equity_bhav_copy(trade_date="DD-MM-YYYY")
"""


from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from indian_quant.schemas import (
    AdjustmentStatus,
    Exchange,
    MarketBar,
    QualityStatus,
    Segment,
    Timeframe,
    make_instrument_id,
)


class SourceBlockedError(RuntimeError):
    """Raised when an upstream serves an anti-bot page instead of data."""


# BSE series -> canonical segment mapping
SERIES_SEGMENT: dict[str, Segment] = {
    "B": Segment.EQ,
    "A": Segment.EQ,
    "X": Segment.EQ,
    "XT": Segment.EQ,
    "MT": Segment.SME,
    "M": Segment.SME,
    "T": Segment.SME,
    "G": Segment.EQ,
    "P": Segment.EQ,
    "IF": Segment.EQ,
    "E": Segment.EQ,
    "Z": Segment.EQ,
    "ZP": Segment.EQ,
    "MS": Segment.SME,
    "R": Segment.EQ,
}

# Equity-only series (for delivery data matching)
CASH_SERIES = {"B", "A", "X", "XT", "G", "P", "IF", "E", "Z", "R"}
SME_SERIES = {"MT", "M", "T", "MS"}
UNIVERSE_SERIES = CASH_SERIES | SME_SERIES


class BseBhavcopyIngester:
    source = "BSE"

    def __init__(self) -> None:
        pass

    def fetch_bhavcopy(self, day: date) -> pd.DataFrame | None:
        """Fetch BSE bhavcopy as DataFrame via bseindia library."""
        try:
            from bseindia import equity

            ddmmYYYY = day.strftime("%d-%m-%Y")
            df = equity.equity_bhav_copy(trade_date=ddmmYYYY)
            return df if df is not None and len(df) > 0 else None
        except Exception:
            return None

    def parse_bhavcopy(
        self,
        df: pd.DataFrame,
        day: date,
        *,
        symbols: set[str] | None = None,
    ) -> list[MarketBar]:
        """Parse BSE bhavcopy DataFrame into canonical daily bars."""
        bars: list[MarketBar] = []
        for _, row in df.iterrows():
            series = str(row.get("SctySrs", "")).strip()
            segment = SERIES_SEGMENT.get(series)
            if segment is None:
                continue
            symbol = str(row.get("TckrSymb", "")).strip().upper()
            if not symbol or (symbols and symbol not in symbols):
                continue
            try:
                o = float(row["OpnPric"])
                h = float(row["HghPric"])
                low = float(row["LwPric"])
                c = float(row["ClsPric"])
                vol = float(row.get("TtlTradgVol") or 0)
            except (KeyError, ValueError, TypeError):
                continue
            if o <= 0 and h <= 0 and low <= 0 and c <= 0:
                continue
            h = max(h, o, c)
            low = min(low, o, c) if low > 0 else min(o, c)
            ts = datetime.fromisoformat(str(row.get("TradDt") or day.isoformat())).replace(
                tzinfo=UTC
            )
            bars.append(
                MarketBar(
                    instrument_id=make_instrument_id(Exchange.BSE, segment, symbol),
                    exchange="BSE",
                    timestamp=ts,
                    timeframe=Timeframe.DAY,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    volume=vol,
                    source=self.source,
                    source_timestamp=ts,
                    ingestion_timestamp=datetime.now(UTC),
                    adjustment_status=AdjustmentStatus.UNADJUSTED,
                    quality_status=QualityStatus.RAW,
                )
            )
        return bars

    def parse_bhavcopy_to_delivery(self, df: pd.DataFrame, day: date) -> dict[str, dict[str, Any]]:
        """Parse BSE bhavcopy into delivery-compatible format.

        BSE bhavcopy doesn't have delivery % separately, but we can extract
        close price, volume, and series for each symbol.
        """
        out: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            series = str(row.get("SctySrs", "")).strip()
            segment = SERIES_SEGMENT.get(series)
            if segment is None:
                continue
            symbol = str(row.get("TckrSymb", "")).strip().upper()
            if not symbol:
                continue
            try:
                close = float(row["ClsPric"])
                vol = float(row.get("TtlTradgVol") or 0)
            except (KeyError, ValueError, TypeError):
                continue
            if close <= 0:
                continue
            out[symbol] = {
                "series": series,
                "close": close,
                "volume": vol,
                "deliv_pct": None,  # BSE bhavcopy doesn't have delivery %
            }
        return out
