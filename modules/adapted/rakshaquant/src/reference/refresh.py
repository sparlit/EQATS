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
The pre-open reference refresh (plan M2.4/M2.5): universe, instrument master and price bands.

* The universe is **pinned** to a snapshot date for the experiment (plan D13): pass
  ``universe_day`` to load that snapshot, or omit it to use today's.
* The instrument master and bands are refreshed daily; when today's download fails the newest
  cached copy is used (stale). Bands are optional (defaults apply); a missing master falls back
  to a Rs 0.05 tick for every instrument. Every degradation is reported for an alert.
"""


from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx2
from src.domain.events import Alert
from src.domain.sink import EventSink
from src.reference.bands import BANDS_NAME, BandTable, fetch_bands, parse_bands
from src.reference.download import ReferenceDataError, Snapshot, latest_snapshot, snapshot_path
from src.reference.instruments import (
    SCRIP_MASTER_NAME,
    InstrumentSet,
    build_instruments,
    fetch_master,
    parse_master,
)
from src.reference.universe import NIFTY50_NAME, UniverseMember, fetch_universe, load_universe


@dataclass(frozen=True)
class ReferenceData:
    universe: list[UniverseMember]
    universe_day: date
    instruments: InstrumentSet
    snapshots: dict[str, Snapshot] = field(default_factory=dict)
    problems: dict[str, str] = field(default_factory=dict)  # alert key -> message


async def refresh_reference(
    reference_dir: Path,
    day: date,
    *,
    universe_day: date | None = None,
    client: httpx2.AsyncClient | None = None,
) -> ReferenceData:
    """Load the pinned (or today's) universe and today's master and bands.

    Raises :class:`ReferenceDataError` only when no universe is available at all.
    """
    problems: dict[str, str] = {}
    snapshots: dict[str, Snapshot] = {}

    if universe_day is not None:
        pinned = snapshot_path(reference_dir, NIFTY50_NAME, universe_day, "csv")
        if not pinned.exists():
            raise ReferenceDataError(f"pinned universe snapshot {pinned.name} is missing")
        universe, used_day = load_universe(pinned), universe_day
    else:
        universe, snap = await fetch_universe(reference_dir, day, client=client)
        snapshots["universe"], used_day = snap, snap.day
        if not snap.fresh:
            problems["reference_stale:universe"] = (
                f"universe from {snap.day} (today's download failed: {snap.error})"
            )

    master = None
    try:
        master, snap = await fetch_master(reference_dir, day, client=client)
        snapshots["instrument_master"] = snap
        if not snap.fresh:
            problems["reference_stale:instrument_master"] = (
                f"instrument master from {snap.day} (today's download failed: {snap.error})"
            )
    except ReferenceDataError as exc:
        problems["reference_missing:instrument_master"] = f"{exc}; using a Rs 0.05 tick for all"

    bands: BandTable | None = None
    try:
        bands, snap = await fetch_bands(reference_dir, day, client=client)
        snapshots["bands"] = snap
        if not snap.fresh:
            problems["reference_stale:bands"] = f"price bands from {snap.day} ({snap.error})"
    except ReferenceDataError as exc:
        problems["reference_missing:bands"] = f"{exc}; using per-series default bands"

    instruments = build_instruments(universe, master, bands)
    if instruments.unmapped:
        problems["reference_unmapped"] = (
            f"{len(instruments.unmapped)} symbols missing from the instrument master "
            f"(fallback tick, no broker token): {', '.join(instruments.unmapped)}"
        )
    return ReferenceData(universe, used_day, instruments, snapshots, problems)


def alert_reference(data: ReferenceData, sink: EventSink) -> None:
    for key, message in sorted(data.problems.items()):
        sink.emit(Alert(level="WARNING", key=key, message=message), source="reference")


def load_reference_offline(reference_dir: Path, day: date) -> InstrumentSet | None:
    """The newest cached universe, instrument master and bands dated on or before ``day`` - no
    network (for replays). ``None`` when no universe snapshot is cached."""
    universe = latest_snapshot(reference_dir, NIFTY50_NAME, "csv", day)
    if universe is None:
        return None
    master_snap = latest_snapshot(reference_dir, SCRIP_MASTER_NAME, "csv", day)
    bands_snap = latest_snapshot(reference_dir, BANDS_NAME, "csv", day)
    master = parse_master(master_snap[1].read_bytes()) if master_snap else None
    bands = parse_bands(bands_snap[1].read_bytes()) if bands_snap else None
    return build_instruments(load_universe(universe[1]), master, bands)
