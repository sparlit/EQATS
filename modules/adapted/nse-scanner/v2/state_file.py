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


"""Git-persisted V2 portfolio state for disposable GitHub Actions runners."""

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

from .portfolio_store import PortfolioStore

STATE_TABLES = ("v2_positions", "v2_position_events", "v2_watchlist_memory", "v2_portfolio_snapshots")


def export_state_file(db_path: str | Path, output_path: str | Path) -> Path:
    """Write only V2 state tables, not the large reusable market-history database."""
    store = PortfolioStore(db_path)
    store.initialize()
    payload: dict[str, object] = {"schema_version": 1, "exported_at": datetime.now(UTC).isoformat(), "tables": {}}
    with store.connect() as conn:
        tables = payload["tables"]
        assert isinstance(tables, dict)
        for table in STATE_TABLES:
            tables[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()]
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(destination)
    return destination


def restore_state_file(db_path: str | Path, input_path: str | Path) -> bool:
    """Restore the prior V2 state before a scheduled run. Missing state is valid on day one."""
    source = Path(input_path)
    if not source.exists():
        return False
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("tables"), dict):
        msg = "unsupported V2 state file"
        raise ValueError(msg)
    store = PortfolioStore(db_path)
    store.initialize()
    with store.connect() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in reversed(STATE_TABLES):
            conn.execute(f"DELETE FROM {table}")
        for table in STATE_TABLES:
            rows = payload["tables"].get(table, [])
            if not rows:
                continue
            columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            usable = [column for column in columns if column in rows[0]]
            placeholders = ",".join("?" for _ in usable)
            conn.executemany(
                f"INSERT INTO {table} ({','.join(usable)}) VALUES ({placeholders})",
                [tuple(row.get(column) for column in usable) for row in rows],
            )
        conn.execute("PRAGMA foreign_keys=ON")
    return True
