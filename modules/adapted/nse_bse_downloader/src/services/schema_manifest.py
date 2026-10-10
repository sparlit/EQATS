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


"""The marker that says what a published folder's columns mean.

Daily files are headerless, and three generations of the contract can sit in
one folder at once: the original seven columns, the nine that added delivery
or open interest, and the eleven that added turnover and previous close.
`validate_daily_output` accepts all of them, so without a marker "valid" says
nothing about which one a file is -- and a consumer reading column nine has no
way to know whether it holds a delivery quantity or a turnover.

A header row would answer that, and would also break every tool that reads
these files positionally today.  So the answer goes beside the data instead:
one `SCHEMA.json` per segment folder, naming the columns of every generation
this application has written, so any file can be read by counting its columns
and looking the width up here.
"""


import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical_data import (
    EQUITY_DAILY_COLUMNS,
    FO_DAILY_COLUMNS,
    INDEX_DAILY_COLUMNS,
)

SCHEMA_FILENAME = "SCHEMA.json"

#: Version of the manifest document itself, not of the data it describes.
SCHEMA_MANIFEST_VERSION = 1


def daily_columns_for(segment: str) -> list[str]:
    """The full current column contract for one segment."""

    segment = segment.upper()
    if segment == "FO":
        return list(FO_DAILY_COLUMNS)
    if segment == "INDEX":
        return list(INDEX_DAILY_COLUMNS)
    return list(EQUITY_DAILY_COLUMNS)


def generations_for(segment: str) -> dict[int, list[str]]:
    """Every published width for one segment, oldest generation first.

    Keyed by generation rather than by width because the width alone is what
    a reader has; the point of the mapping is to turn one into the other.
    """

    columns = daily_columns_for(segment)
    widths = [7, 9, 11] if len(columns) >= 11 else [7, len(columns)]
    return {
        number: columns[:width]
        for number, width in enumerate(dict.fromkeys(widths), start=1)
        if width <= len(columns)
    }


def manifest_payload(
    exchange: str, segment: str, *, version: str, timestamp: str
) -> dict[str, Any]:
    columns = daily_columns_for(segment)
    generations = generations_for(segment)
    return {
        "version": SCHEMA_MANIFEST_VERSION,
        "exchange": exchange.upper(),
        "segment": segment.upper(),
        "written_by": version,
        "updated_at": timestamp,
        "current_generation": max(generations),
        "columns": columns,
        "generations": {str(number): names for number, names in sorted(generations.items())},
        "note": (
            "Files here are headerless CSV. Count a row's columns and look the "
            "width up in 'generations' to know what each field is."
        ),
    }


def _stable(payload: dict[str, Any]) -> dict[str, Any]:
    """The part of a manifest that decides whether it needs rewriting."""

    return {key: value for key, value in payload.items() if key != "updated_at"}


def read_manifest(folder: Path) -> dict[str, Any] | None:
    """Return one folder's manifest, or None if it is absent or unusable.

    Deliberately plain: a caller that only wants to *report* a damaged marker
    must not be the thing that moves it aside.
    """

    path = Path(folder) / SCHEMA_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_manifest(folder: Path, exchange: str, segment: str) -> Path | None:
    """Write or refresh one segment's manifest, returning it if it changed.

    Rewriting an unchanged manifest on every launch would put a new mtime on a
    file in the user's data folder for no reason, and would make every backup
    and sync see a change that is not one.
    """

    from version import get_version

    folder = Path(folder)
    if not folder.is_dir():
        return None
    payload = manifest_payload(
        exchange,
        segment,
        version=get_version(),
        timestamp=datetime.now(UTC).isoformat(),
    )
    existing = read_manifest(folder)
    if existing is not None and _stable(existing) == _stable(payload):
        return None

    path = folder / SCHEMA_FILENAME
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
