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


"""
Price bands (plan M2.4). NSE's daily file (verified 2026-10-02):
``https://nsearchives.nseindia.com/content/equities/sec_list.csv`` with columns
``Symbol, Series, Security Name, Band, Remarks``; ``Band`` is 2/5/10/20/40 (%) or ``No Band``.
F&O stocks (every NIFTY 50 name) are ``No Band``: they have dynamic price bands instead, which
we represent as ``None``. When the file is unavailable a per-series default table is used.
"""


import csv
import io
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import httpx2
from src.reference.download import Snapshot, fetch_snapshot

BANDS_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"
BANDS_NAME = "nse_bands"

# Fallback when the NSE file is unavailable. EQ: None = treat as a dynamic-band (F&O) stock,
# which is true of the whole month-1 universe. Trade-for-trade series are typically 5%.
DEFAULT_BAND_BY_SERIES: Mapping[str, float | None] = {"EQ": None, "BE": 5.0, "BZ": 5.0}

BandTable = dict[tuple[str, str], float | None]


def parse_bands(body: bytes) -> BandTable:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    if not {"Symbol", "Series", "Band"} <= set(reader.fieldnames or []):
        raise ValueError("band file lacks Symbol/Series/Band columns")
    table: BandTable = {}
    for row in reader:
        raw = row["Band"].strip()
        if raw.lower() == "no band":
            band: float | None = None
        else:
            band = float(raw)
            if band <= 0:
                raise ValueError(f"non-positive band for {row['Symbol']}: {raw}")
        table[(row["Symbol"].strip(), row["Series"].strip())] = band
    if not table:
        raise ValueError("empty band file")
    return table


async def fetch_bands(
    reference_dir: Path, day: date, *, client: httpx2.AsyncClient | None = None
) -> tuple[BandTable, Snapshot]:
    snapshot = await fetch_snapshot(
        BANDS_URL,
        directory=reference_dir,
        name=BANDS_NAME,
        ext="csv",
        day=day,
        client=client,
        validate=parse_bands,
    )
    return parse_bands(snapshot.path.read_bytes()), snapshot


def band_for(symbol: str, series: str, table: BandTable | None) -> float | None:
    """The scrip's band in %, None for dynamic-band (F&O) stocks or when unknown."""
    if table is not None and (symbol, series) in table:
        return table[(symbol, series)]
    return DEFAULT_BAND_BY_SERIES.get(series)
