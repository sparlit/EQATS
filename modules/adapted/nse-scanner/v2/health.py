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


"""Operational health checks for the V2 scanner database and outputs."""

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class HealthReport:
    status: str
    checked_at: str
    database_exists: bool
    integrity_ok: bool
    latest_price_date: str | None
    latest_index_date: str | None
    active_positions: int
    watchlist_rows: int
    price_age_days: int | None
    index_age_days: int | None
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _latest(conn: sqlite3.Connection, table: str, column: str) -> str | None:
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in names:
        return None
    value = conn.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
    return str(value) if value else None


def build_health_report(db_path: str | Path, as_of: date | str | None = None) -> HealthReport:
    path = Path(db_path)
    checked = pd.Timestamp(as_of or date.today()).date()
    if not path.exists():
        return HealthReport(
            status="CRITICAL",
            checked_at=checked.isoformat(),
            database_exists=False,
            integrity_ok=False,
            latest_price_date=None,
            latest_index_date=None,
            active_positions=0,
            watchlist_rows=0,
            price_age_days=None,
            index_age_days=None,
            warnings=("database_missing",),
        )

    warnings: list[str] = []
    with sqlite3.connect(str(path)) as conn:
        integrity_ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        price_table = (
            "daily_prices_v2" if "daily_prices_v2" in names else "daily_prices" if "daily_prices" in names else None
        )
        price_col = "trade_date" if price_table == "daily_prices_v2" else "date"
        latest_price = _latest(conn, price_table, price_col) if price_table else None
        latest_index = _latest(conn, "index_perf", "date")
        active = (
            int(
                conn.execute("SELECT COUNT(*) FROM v2_positions WHERE state NOT IN ('CLOSED','CANCELLED')").fetchone()[
                    0
                ]
            )
            if "v2_positions" in names
            else 0
        )
        watches = (
            int(conn.execute("SELECT COUNT(*) FROM v2_watchlist_memory WHERE active=1").fetchone()[0])
            if "v2_watchlist_memory" in names
            else 0
        )

    price_age = (checked - pd.Timestamp(latest_price).date()).days if latest_price else None
    index_age = (checked - pd.Timestamp(latest_index).date()).days if latest_index else None
    if not integrity_ok:
        warnings.append("database_integrity_failed")
    if latest_price is None:
        warnings.append("price_history_missing")
    elif price_age is not None and price_age > 4:
        warnings.append("price_history_stale")
    if latest_index is None:
        warnings.append("index_history_missing")
    elif index_age is not None and index_age > 4:
        warnings.append("index_history_stale")

    critical = not integrity_ok or latest_price is None
    status = "CRITICAL" if critical else "DEGRADED" if warnings else "HEALTHY"
    return HealthReport(
        status=status,
        checked_at=checked.isoformat(),
        database_exists=True,
        integrity_ok=integrity_ok,
        latest_price_date=latest_price,
        latest_index_date=latest_index,
        active_positions=active,
        watchlist_rows=watches,
        price_age_days=price_age,
        index_age_days=index_age,
        warnings=tuple(warnings),
    )


def write_health_report(report: HealthReport, output_path: str | Path = "output/v2_health.json") -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path
