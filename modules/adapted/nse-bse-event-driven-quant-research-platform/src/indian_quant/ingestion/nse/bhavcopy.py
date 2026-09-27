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


"""NSE UDiFF bhavcopy ingestion: exchange archives CDN -> canonical bars.

The NSE quote/chart APIs are aggressively bot-blocked; the public archives
CDN is not. This is therefore the primary historical-bars source, and it is
also the most research-grade one: full-exchange files with ISINs.

Sources:
    CM UDiFF:    https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
    Delivery:    https://narchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
"""


import contextlib
import csv
import io
import zipfile
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import httpx

from indian_quant.schemas import (
    AdjustmentStatus,
    Exchange,
    MarketBar,
    QualityStatus,
    Segment,
    Timeframe,
    make_instrument_id,
)

if TYPE_CHECKING:
    from indian_quant.storage.raw_store import RawStore

CM_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
DELIVERY_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"

# Series -> canonical segment mapping (verified empirically against live
# UDiFF files, Aug 2026: SM/ST are the NSE Emerge/SME series).
SERIES_SEGMENT = {
    "EQ": Segment.EQ,
    "BE": Segment.EQ,
    "BZ": Segment.EQ,
    "SM": Segment.SME,
    "ST": Segment.SME,
}
CASH_SERIES = {"EQ", "BE", "BZ"}
UNIVERSE_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "*/*",
}


class BhavcopyIngester:
    source = "NSE"

    def __init__(self, raw_store: RawStore, *, timeout: float = 60.0) -> None:
        self.raw_store = raw_store
        self.timeout = timeout

    def fetch_delivery_csv(self, day: date) -> tuple[str | None, str]:
        """Fetch the sec_bhavdata_full delivery file; returns (csv_text, hash)."""
        ddmmyyyy = day.strftime("%d%m%Y")
        resp = httpx.get(
            DELIVERY_URL.format(ddmmyyyy=ddmmyyyy),
            headers=HEADERS,
            timeout=self.timeout,
            follow_redirects=True,
        )
        if resp.status_code in (404, 403):
            return None, f"unavailable:{resp.status_code}"
        resp.raise_for_status()
        text = resp.text
        if text.lstrip()[:1] == "<":
            return None, "blocked"
        _, digest = self.raw_store.save(
            source="nse",
            tool="bhavcopy_delivery_sec",
            payload=text.encode(),
            ext="csv",
            request_meta={"date": day.isoformat(), "url": str(resp.url)},
        )
        return text, digest

    def fetch_cm_zip(self, day: date) -> tuple[bytes | None, str]:
        """Download the CM bhavcopy zip for a trading day; persist raw bytes."""
        yyyymmdd = day.strftime("%Y%m%d")
        resp = httpx.get(
            CM_URL.format(yyyymmdd=yyyymmdd),
            headers=HEADERS,
            timeout=self.timeout,
            follow_redirects=True,
        )
        if resp.status_code in {404, 403}:
            return None, f"unavailable:{resp.status_code}"
        resp.raise_for_status()
        _, digest = self.raw_store.save(
            source="nse",
            tool="bhavcopy_cm_udiff",
            payload=resp.content,
            ext="zip",
            request_meta={"date": day.isoformat(), "url": str(resp.url)},
        )
        return resp.content, digest

    def parse_cm_zip(
        self,
        payload: bytes,
        day: date,
        *,
        symbols: set[str] | None = None,
        series: set[str] | None = None,
    ) -> list[MarketBar]:
        """Parse a CM UDiFF zip into canonical daily bars."""
        wanted_series = series or UNIVERSE_SERIES
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".csv"))
            reader = csv.DictReader(io.StringIO(zf.read(name).decode("utf-8-sig")))
            bars: list[MarketBar] = []
            for row in reader:
                scry = row.get("SctySrs")
                if scry not in wanted_series:
                    continue
                segment = SERIES_SEGMENT.get(scry, Segment.EQ)
                symbol = (row.get("TckrSymb") or "").strip()
                if not symbol or (symbols and symbol.upper() not in symbols):
                    continue
                try:
                    o = float(row["OpnPric"])
                    h = float(row["HghPric"])
                    low = float(row["LwPric"])
                    c = float(row["ClsPric"])
                    vol = float(row.get("TtlTradgVol") or 0)
                except (KeyError, ValueError, TypeError):
                    continue
                ts = datetime.fromisoformat(str(row.get("TradDt") or day.isoformat())).replace(tzinfo=UTC)
                bars.append(
                    MarketBar(
                        instrument_id=make_instrument_id(Exchange.NSE, segment, symbol.upper()),
                        exchange="NSE",
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

    def ingest_range(
        self,
        from_date: date,
        to_date: date,
        *,
        symbols: set[str] | None = None,
    ) -> list[MarketBar]:
        """Ingest every available trading day in [from_date, to_date]."""
        all_bars: list[MarketBar] = []
        cursor = from_date
        while cursor <= to_date:
            if cursor.weekday() < 5:
                payload, _ = self.fetch_cm_zip(cursor)
                if payload:
                    all_bars.extend(self.parse_cm_zip(payload, cursor, symbols=symbols))
                else:
                    print(f"  no bhavcopy for {cursor} (holiday/unlisted)")
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return all_bars


def parse_delivery_csv(text: str) -> dict[str, dict[str, Any]]:
    """Parse sec_bhavdata_full delivery CSV.

    Returns {symbol: {"close": float, "deliv_pct": float|None}}.
    """
    out: dict[str, dict[str, float]] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        symbol = cleaned.get("SYMBOL", "")
        series = cleaned.get("SERIES", "")
        if not symbol or series not in UNIVERSE_SERIES:
            continue
        rec: dict[str, Any] = {"series": cleaned.get("SERIES", "")}
        try:
            rec["close"] = float(cleaned.get("CLOSE_PRICE", ""))
        except ValueError:
            continue
        pct = cleaned.get("DELIV_PER", "")
        if pct not in ("", "-"):
            with contextlib.suppress(ValueError):
                rec["deliv_pct"] = float(pct)
        with contextlib.suppress(ValueError):
            rec["volume"] = float(cleaned.get("TTL_TRD_QNTY", "") or 0)
        out[symbol] = rec
    return out


def udiff_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if v not in ("", "-")}
