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


"""Audit whether stored point-in-time data can support a defensible V3 backtest."""

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    price_sessions: int
    price_symbols: int
    delivery_coverage_pct: float
    turnover_coverage_pct: float
    market_cap_symbols: int
    fundamental_symbols: int
    index_sessions: int
    shares_symbols: int
    pledge_symbols: int
    point_in_time_market_cap_symbols: int
    blockers: tuple[str, ...]


def audit(db_path: str) -> ReadinessReport:
    blockers: list[str] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        price_table = (
            "daily_prices_v2" if "daily_prices_v2" in tables else "daily_prices" if "daily_prices" in tables else None
        )
        if not price_table:
            return ReadinessReport("BLOCKED", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ("price_table_missing",))
        date_col = "trade_date" if price_table == "daily_prices_v2" else "date"
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({price_table})")}
        total = conn.execute(f"SELECT COUNT(*) FROM {price_table}").fetchone()[0]
        sessions = conn.execute(f"SELECT COUNT(DISTINCT {date_col}) FROM {price_table}").fetchone()[0]
        symbols = conn.execute(f"SELECT COUNT(DISTINCT symbol) FROM {price_table}").fetchone()[0]

        def coverage(column: str) -> float:
            if column not in columns or not total:
                return 0.0
            available = conn.execute(f"SELECT COUNT(*) FROM {price_table} WHERE {column} IS NOT NULL").fetchone()[0]
            return round(available / total * 100.0, 2)

        delivery, turnover = coverage("delivery_pct"), coverage("turnover_lacs")
        caps = 0
        if "symbol_master_v2" in tables:
            master_columns = {row[1] for row in conn.execute("PRAGMA table_info(symbol_master_v2)")}
            if "market_cap_cr" in master_columns:
                caps = conn.execute("SELECT COUNT(*) FROM symbol_master_v2 WHERE market_cap_cr IS NOT NULL").fetchone()[
                    0
                ]
        fundamentals = (
            conn.execute("SELECT COUNT(DISTINCT symbol) FROM fundamental_snapshots_v3").fetchone()[0]
            if "fundamental_snapshots_v3" in tables
            else 0
        )
        index_sessions = (
            conn.execute("SELECT COUNT(DISTINCT date) FROM index_perf").fetchone()[0] if "index_perf" in tables else 0
        )
        shares = (
            conn.execute("SELECT COUNT(DISTINCT symbol) FROM shares_outstanding_v3").fetchone()[0]
            if "shares_outstanding_v3" in tables
            else 0
        )
        pledges = (
            conn.execute("SELECT COUNT(DISTINCT symbol) FROM promoter_pledge_v3").fetchone()[0]
            if "promoter_pledge_v3" in tables
            else 0
        )
        point_caps = (
            conn.execute("SELECT COUNT(DISTINCT symbol) FROM market_cap_snapshots_v3").fetchone()[0]
            if "market_cap_snapshots_v3" in tables
            else 0
        )
    if sessions < 400:
        blockers.append("fewer_than_400_price_sessions")
    if delivery < 95:
        blockers.append("delivery_coverage_below_95_percent")
    if turnover < 95:
        blockers.append("turnover_coverage_below_95_percent")
    if caps < max(1, int(symbols * 0.8)):
        blockers.append("market_cap_coverage_below_80_percent")
    if fundamentals < max(1, int(symbols * 0.5)):
        blockers.append("fundamental_coverage_below_50_percent")
    if index_sessions < 400:
        blockers.append("fewer_than_400_official_index_sessions")
    if point_caps < max(1, int(symbols * 0.8)):
        blockers.append("point_in_time_market_cap_coverage_below_80_percent")
    if shares < max(1, int(symbols * 0.8)):
        blockers.append("shares_outstanding_coverage_below_80_percent")
    if pledges < max(1, int(symbols * 0.5)):
        blockers.append("promoter_pledge_coverage_below_50_percent")
    return ReadinessReport(
        "READY" if not blockers else "BLOCKED",
        sessions,
        symbols,
        delivery,
        turnover,
        caps,
        fundamentals,
        index_sessions,
        shares,
        pledges,
        point_caps,
        tuple(blockers),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    args = parser.parse_args()
    report = audit(args.db)
    print(json.dumps(asdict(report), indent=2))
    return 0 if report.status == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
