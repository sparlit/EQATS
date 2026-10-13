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


"""Upstox REST client: Historical Candle Data V3 + Market Quotes V2.

Endpoints:
  GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
  GET /v2/market-quote/quotes?instrument_key=...
  GET /v2/market-quote/ltp?instrument_key=...
Auth: Bearer access token. Instrument keys use the canonical Upstox format,
e.g. ``NSE_EQ|INE002A01018`` - which is why our canonical ids were designed
with the same EXCHANGE_SEGMENT|LOCAL_ID shape.
"""


from datetime import UTC, date, datetime
from typing import Any

import httpx

from indian_quant.schemas import AdjustmentStatus, MarketBar, Timeframe
from indian_quant.storage.raw_store import RawStore

BASE_URL = "https://api.upstox.com/v3"

UNIT_FOR_TIMEFRAME = {
    Timeframe.MIN_1: ("minutes", 1),
    Timeframe.MIN_5: ("minutes", 5),
    Timeframe.MIN_15: ("minutes", 15),
    Timeframe.MIN_30: ("minutes", 30),
    Timeframe.MIN_60: ("hours", 1),
    Timeframe.DAY: ("days", 1),
    Timeframe.WEEK: ("weeks", 1),
    Timeframe.MONTH: ("months", 1),
}


class UpstoxRestClient:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        raw_store: RawStore | None = None,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.access_token = access_token
        self.raw_store = raw_store
        self.base_url = base_url
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def historical_candles(
        self,
        instrument_key: str,
        unit: str,
        interval: int | str,
        to_date: date | str,
        from_date: date | str | None = None,
    ) -> dict[str, Any]:
        to_s = to_date.isoformat() if isinstance(to_date, date) else to_date
        path = f"/historical-candle/{instrument_key}/{unit}/{interval}/{to_s}"
        if from_date is not None:
            from_s = from_date.isoformat() if isinstance(from_date, date) else from_date
            path += f"/{from_s}"
        resp = httpx.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if self.raw_store:
            body = resp.content
            self.raw_store.save(
                source="upstox",
                tool="historical_candle_v3",
                payload=body,
                request_meta={"instrument_key": instrument_key, "unit": unit, "interval": interval},
            )
        return payload

    def candles_to_bars(
        self,
        payload: dict[str, Any],
        *,
        instrument_id: str,
        exchange: str,
        timeframe: Timeframe,
        normalize_daily_to_utc: bool = True,
    ) -> list[MarketBar]:
        """Convert Upstox candle arrays into canonical bars.

        Daily-and-coarser candles arrive stamped at IST midnight; they are
        re-stamped to UTC midnight (same calendar date) so every daily bar in
        the lake shares one timestamp convention. Intraday timeframes keep
        their true instants untouched.
        """

        candles = (payload.get("data") or {}).get("candles") or []
        bars: list[MarketBar] = []
        for row in candles:
            if len(row) < 6:
                continue
            ts_raw, o, h, low, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
            oi = row[6] if len(row) > 6 else None
            ist_ts = datetime.fromisoformat(str(ts_raw))
            if normalize_daily_to_utc and timeframe in (
                Timeframe.DAY,
                Timeframe.WEEK,
                Timeframe.MONTH,
            ):
                day = ist_ts.date()
                ts = datetime(day.year, day.month, day.day, tzinfo=UTC)
            else:
                ts = ist_ts.astimezone(UTC)
            bars.append(
                MarketBar(
                    instrument_id=instrument_id,
                    exchange=exchange,
                    timestamp=ts,
                    timeframe=timeframe,
                    open=float(o),
                    high=float(h),
                    low=float(low),
                    close=float(c),
                    volume=float(v),
                    open_interest=float(oi) if oi is not None else None,
                    source="UPSTOX",
                    source_timestamp=ist_ts.astimezone(UTC),
                    ingestion_timestamp=datetime.now(UTC),
                    adjustment_status=AdjustmentStatus.UNADJUSTED,
                )
            )
        return bars

    def get_bars(
        self,
        *,
        instrument_key: str,
        instrument_id: str,
        exchange: str = "NSE",
        timeframe: Timeframe = Timeframe.DAY,
        to_date: date | str,
        from_date: date | str | None = None,
    ) -> list[MarketBar]:
        unit, interval = UNIT_FOR_TIMEFRAME[timeframe]
        payload = self.historical_candles(instrument_key, unit, interval, to_date, from_date)
        return self.candles_to_bars(
            payload, instrument_id=instrument_id, exchange=exchange, timeframe=timeframe
        )

    def get_quotes(self, instrument_keys: list[str]) -> dict[str, dict[str, Any]]:
        """GET /v2/market-quote/quotes — full market quotes.

        Returns dict keyed by symbol (e.g. 'NSE_EQ:NHPC') with last_price,
        ohlc, volume, depth, circuit limits, etc. Supports up to 500 instruments.
        """
        keys_csv = ",".join(instrument_keys)
        resp = httpx.get(
            "https://api.upstox.com/v2/market-quote/quotes",
            params={"instrument_key": keys_csv},
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("data") or {}

    def get_ltp(self, instrument_keys: list[str]) -> dict[str, dict[str, Any]]:
        """GET /v2/market-quote/ltp — lightweight LTP-only quotes.

        Returns dict keyed by symbol with just last_price per instrument.
        Faster than get_quotes when only LTP is needed.
        """
        keys_csv = ",".join(instrument_keys)
        resp = httpx.get(
            "https://api.upstox.com/v2/market-quote/ltp",
            params={"instrument_key": keys_csv},
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("data") or {}
