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


"""Opt-in integration used by scanner runners and the offline review command."""

import json
import sqlite3
from pathlib import Path

import pandas as pd
from v2.tradeability import evaluate_tradeability

from .adapters import ladder_candidates, penny_candidates
from .ledger import LedgerConfig, advance
from .render import render_messages


def market_bars(database, day: str) -> dict:
    """All holdings get bars, even when outside today's scanner price band.

    Current eligibility gates block new entries; terminal events freeze holdings
    for review. Candle lock checks are conservative proxies, not order-book proof.
    """
    # Execution/accounting needs only this session and the prior close; loading
    # the full indicator warm-up history on every ledger update is unnecessary.
    uri = Path(database.path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        table = database.price_table(conn)
        date_col = "trade_date" if table == "daily_prices_v2" else "date"
        sessions = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT {date_col} FROM {table} WHERE {date_col} <= ? ORDER BY {date_col} DESC LIMIT 2",
                (day,),
            )
        ]
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        prev_column = ",prev_close" if "prev_close" in columns else ""
        placeholders = ",".join("?" for _ in sessions)
        prices = pd.read_sql_query(
            f"SELECT symbol,{date_col} AS trade_date,open,high,low,close,volume{prev_column} "
            f"FROM {table} WHERE {date_col} IN ({placeholders}) ORDER BY symbol,{date_col}",
            conn,
            params=sessions,
        )
    if prices.empty:
        msg = "No market data for portfolio accounting"
        raise ValueError(msg)
    prices = prices.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    latest = prices["trade_date"].max().date().isoformat()
    if latest != day:
        msg = f"Portfolio date {day} has no completed market session (latest {latest})"
        raise ValueError(msg)
    master = database.load_symbol_master(day)
    metadata = {str(r["symbol"]): r.to_dict() for _, r in master.iterrows()}
    restricted = database.load_restricted_symbols(day)
    registry = database.load_lifecycle_registry()
    calendar = tuple(sorted(prices["trade_date"].dt.date.astype(str).unique()))
    bars = {}
    for symbol, frame in prices.groupby("symbol", sort=True):
        frame = frame.sort_values("trade_date")
        row = frame.iloc[-1]
        if row["trade_date"].date().isoformat() != day:
            continue
        gate = evaluate_tradeability(
            str(symbol),
            frame,
            market_date=day,
            master_row=metadata.get(str(symbol)),
            restricted_reason=restricted.get(str(symbol)),
            lifecycle_event=registry.get(str(symbol)),
            session_calendar=calendar,
            require_metadata=bool(metadata),
        )
        close, op = float(row["close"]), float(row["open"])
        prev = float(frame.iloc[-2]["close"]) if len(frame) > 1 else op
        prev_raw = row.get("prev_close")
        if prev_raw is not None and pd.notna(prev_raw) and float(prev_raw) > 0:
            prev = float(prev_raw)
        gap = (op / prev - 1) * 100 if prev > 0 else 0
        one_price = float(row["high"]) == float(row["low"])
        bars[str(symbol)] = {
            "date": day,
            "open": op,
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": close,
            "prev_close": prev,
            "entry_allowed": bool(gate.eligible and not gate.entry_blocked),
            "entry_blocked": bool(one_price or (close == float(row["high"]) and gap >= 9.5)),
            "exit_blocked": bool(one_price or (close == float(row["low"]) and gap <= -9.5)),
            "review_required": bool(
                gate.stage == "CORPORATE_LIFECYCLE" or gate.detail == "MATERIAL_CORPORATE_ACTION_REVIEW"
            ),
            "metadata_available": bool(metadata),
        }
    return bars


def update_portfolio(
    scanner: str,
    report: dict,
    database,
    path: str | Path,
    *,
    config: LedgerConfig = LedgerConfig(),
    legacy: list[dict] | None = None,
    provenance: str = "FORWARD_PAPER_COHORT",
) -> dict:
    day = report.get("as_of_date")
    if not day:
        msg = "Signal report has no date"
        raise ValueError(msg)
    candidates = penny_candidates(report) if scanner == "Penny" else ladder_candidates(report)
    # Refuse to skip an exchange session and miss a stop/target on a held trade.
    uri = Path(database.path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        table = database.price_table(conn)
        date_col = "trade_date" if table == "daily_prices_v2" else "date"
        previous_session = conn.execute(f"SELECT MAX({date_col}) FROM {table} WHERE {date_col} < ?", (day,)).fetchone()[
            0
        ]
    return advance(
        path,
        scanner,
        day,
        market_bars(database, day),
        candidates,
        config=config,
        legacy=legacy,
        provenance=provenance,
        previous_session=previous_session,
    )


def write_reports(snapshot: dict, directory: str | Path) -> list[str]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    name = snapshot["scanner"].lower().replace(" ", "_")
    text = json.dumps(snapshot, indent=2, allow_nan=False)
    temporary = target / (name + ".json.tmp")
    temporary.write_text(text + "\n", encoding="utf-8")
    temporary.replace(target / (name + ".json"))
    messages = render_messages(snapshot)
    (target / (name + ".html")).write_text("\n<hr/>\n".join(messages), encoding="utf-8")
    return messages
