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


"""Tolerant parsing helpers for upstream NSE/BSE payloads.

Upstream field naming varies across endpoints (upper/lower case, legacy
aliases). Resolution here is explicit: only known aliases are accepted,
everything else lands in ``extra`` so nothing silently mixes.
"""


import csv
import io
import json
from datetime import UTC, date, datetime
from typing import Any

CANDIDATE_TS_FIELDS = [
    "timestamp",
    "TIMESTAMP",
    "tradeDate",
    "trade_date",
    "date",
    "DATE",
    "lastUpdateTime",
    "sortDate",
    "sort_date",
    "an_dt",
    "publishedAt",
    "TradDt",
]
CANDIDATE_OHLC = {
    "open": ["open", "OPEN", "openPrice"],
    "high": ["high", "HIGH", "dayHigh"],
    "low": ["low", "LOW", "dayLow"],
    "close": ["close", "CLOSE", "closePrice", "lastPrice", "last_price", "CM_LAST_PRC"],
    "volume": ["volume", "VOLUME", "totalTradedVolume", "TOTTRDQTY", "tradedVolume"],
}


def extract_record_list(payload: Any) -> list[dict[str, Any]]:
    """Pull a list of dict records out of an arbitrary MCP tool payload."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("data", "records", "items", "result"):
        inner = payload.get(key)
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
        if isinstance(inner, dict):
            for key2 in ("data", "records"):
                inner2 = inner.get(key2)
                if isinstance(inner2, list):
                    return [r for r in inner2 if isinstance(r, dict)]

    if "content" in payload and isinstance(payload["content"], list):
        texts = [c.get("text", "") for c in payload["content"] if isinstance(c, dict)]
        joined = "\n".join(t for t in texts if t)
        try:
            return extract_record_list(json.loads(joined))
        except json.JSONDecodeError:
            return []

    for value in payload.values():
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            return list(value)

    if payload:
        return [payload]
    return []


def resolve_field(record: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in record.items()}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e15 or ts > 1e11:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%d-%b-%Y",
        "%d-%b-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text.split(".")[0][:19], fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    ts = parse_timestamp(value)
    return ts.date() if ts else None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_candle_rows(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Parse [ts, open, high, low, close, volume?] candle arrays."""
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        rec: dict[str, Any] = {
            "timestamp": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
        }
        if len(row) >= 6:
            rec["volume"] = row[5]
        out.append(rec)
    return out


def parse_bhavcopy_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]
