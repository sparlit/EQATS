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


"""Incremental, NSE-only corporate-action collector.

The endpoint is intentionally treated as an advisory listing: a failure leaves
the existing normalized action history untouched.  The eligibility gate only
blocks material actions that NSE has actually disclosed and that were known on
or before the scan date.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from nse_historical_downloader import HEADERS
from v2.database import V2Database

LISTING_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={from_date}&to_date={to_date}"
)
NORMALIZED_PATH = Path("corporate_data/normalized/corporate_actions.csv")
MATERIAL_ACTION_WORDS = (
    "BONUS",
    "SPLIT",
    "RIGHT",
    "MERGER",
    "AMALGAMATION",
    "DEMERGER",
    "BUYBACK",
    "DELIST",
    "REDUCTION",
)


@dataclass(frozen=True)
class CorporateActionHealth:
    status: str
    listed: int = 0
    normalized: int = 0
    error: str = ""


def _date(value: object) -> str:
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _value(row: dict, *keys: str) -> object:
    lowered = {str(key).lower().replace(" ", ""): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower().replace(" ", ""))
        if value not in (None, ""):
            return value
    return ""


def fetch_listing(start_date: date, end_date: date, session: requests.Session | None = None) -> list[dict]:
    client = session or requests.Session()
    client.headers.update(HEADERS)
    client.get("https://www.nseindia.com", timeout=20)
    url = LISTING_URL.format(from_date=start_date.strftime("%d-%m-%Y"), to_date=end_date.strftime("%d-%m-%Y"))
    response = client.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        msg = "NSE corporate-action listing was not a list"
        raise ValueError(msg)
    return payload


def normalize_listing(rows: list[dict], source_url: str) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        symbol = str(_value(row, "symbol", "symbolName")).strip().upper()
        ex_date = _date(_value(row, "exDate", "ex_date", "recordDate", "record_date"))
        action_type = str(_value(row, "subject", "purpose", "series", "actionType", "action_type")).strip()
        available_date = _date(_value(row, "caBroadcastDate", "broadcastDate", "announcementDate", "announcement_date"))
        if not symbol or not ex_date or not action_type:
            continue
        available_date = available_date or ex_date
        description = json.dumps(row, sort_keys=True, separators=(",", ":"))
        filing_id = hashlib.sha256(f"{source_url}|{symbol}|{ex_date}|{action_type}|{description}".encode()).hexdigest()[
            :32
        ]
        normalized.append(
            {
                "symbol": symbol,
                "ex_date": ex_date,
                "available_date": available_date,
                "action_type": action_type,
                "description": description,
                "source": source_url,
                "filing_id": filing_id,
                "material": any(word in action_type.upper() for word in MATERIAL_ACTION_WORDS),
            }
        )
    return normalized


def _write_normalized(rows: list[dict]) -> None:
    NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(NORMALIZED_PATH) if NORMALIZED_PATH.exists() else pd.DataFrame()
    fresh = pd.DataFrame(rows)
    combined = pd.concat([old, fresh], ignore_index=True, sort=False)
    if combined.empty:
        return
    combined = combined.drop_duplicates(subset=["symbol", "ex_date", "action_type"], keep="last")
    temp = NORMALIZED_PATH.with_suffix(".tmp")
    combined.sort_values(["symbol", "ex_date", "action_type"]).to_csv(temp, index=False)
    temp.replace(NORMALIZED_PATH)


def collect(
    db_path: str | Path, as_of: date, days: int = 7, forward_days: int = 14, session: requests.Session | None = None
) -> CorporateActionHealth:
    start, end = as_of - timedelta(days=days), as_of + timedelta(days=forward_days)
    source_url = LISTING_URL.format(from_date=start.strftime("%d-%m-%Y"), to_date=end.strftime("%d-%m-%Y"))
    try:
        listed = fetch_listing(start, end, session)
        rows = normalize_listing(listed, source_url)
        V2Database(db_path).ensure_v3_schema()
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                """INSERT INTO corporate_actions_v3
                (symbol,ex_date,available_date,action_type,description,source,filing_id)
                VALUES (:symbol,:ex_date,:available_date,:action_type,:description,:source,:filing_id)
                ON CONFLICT(symbol,ex_date,action_type) DO UPDATE SET
                  available_date=excluded.available_date,description=excluded.description,
                  source=excluded.source,filing_id=excluded.filing_id""",
                rows,
            )
        _write_normalized(rows)
        return CorporateActionHealth("FRESH" if rows else "NO_NEW_FILINGS", len(listed), len(rows))
    except Exception as exc:
        return CorporateActionHealth("REUSED_LAST_VALID", error=str(exc))


def as_dict(health: CorporateActionHealth) -> dict:
    return asdict(health)
