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


"""Durable backup and restore helpers for persistent V2 scanner state."""

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path

STATE_TABLES = ("v2_positions", "v2_position_events", "v2_watchlist_memory")


@dataclass(frozen=True)
class BackupResult:
    database_path: str
    backup_path: str
    manifest_path: str
    sha256: str
    table_counts: dict[str, int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with sqlite3.connect(str(path)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in STATE_TABLES:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table in names else 0
    return counts


def create_state_backup(db_path: str | Path, backup_dir: str | Path = "backups/v2") -> BackupResult:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(source)
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = destination_dir / f"v2_state_{stamp}.db"
    with sqlite3.connect(str(source)) as src, sqlite3.connect(str(backup)) as dst:
        src.backup(dst)
    with sqlite3.connect(str(backup)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            backup.unlink(missing_ok=True)
            msg = f"backup integrity check failed: {result}"
            raise RuntimeError(msg)
    checksum = _sha256(backup)
    counts = _counts(backup)
    manifest = backup.with_suffix(".json")
    manifest.write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "source_database": str(source),
                "backup_database": str(backup),
                "sha256": checksum,
                "table_counts": counts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return BackupResult(str(source), str(backup), str(manifest), checksum, counts)


def restore_state_backup(
    backup_path: str | Path,
    db_path: str | Path,
    *,
    expected_sha256: str | None = None,
    keep_existing_copy: bool = True,
) -> Path:
    backup = Path(backup_path)
    destination = Path(db_path)
    if not backup.exists():
        raise FileNotFoundError(backup)
    actual = _sha256(backup)
    if expected_sha256 and actual != expected_sha256:
        msg = "backup checksum mismatch"
        raise ValueError(msg)
    with sqlite3.connect(str(backup)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            msg = f"backup integrity check failed: {result}"
            raise RuntimeError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and keep_existing_copy:
        safety = destination.with_suffix(destination.suffix + ".pre_restore")
        shutil.copy2(destination, safety)
    # SQLite backup avoids replacing an open database file on Windows, while
    # retaining the existing configured path for the local scheduler.
    with sqlite3.connect(str(backup)) as source, sqlite3.connect(str(destination)) as target:
        source.backup(target)
    with sqlite3.connect(str(destination)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            msg = f"restored database integrity check failed: {result}"
            raise RuntimeError(msg)
    return destination
