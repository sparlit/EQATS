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


"""SQLite persistence for V2 watchlist, positions and lifecycle events."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .lifecycle import Position, TradeState

SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_positions (
    trade_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    horizon TEXT NOT NULL,
    state TEXT NOT NULL,
    created_date TEXT NOT NULL,
    updated_date TEXT NOT NULL,
    entry REAL NOT NULL,
    initial_stop REAL NOT NULL,
    stop REAL NOT NULL,
    target1 REAL NOT NULL,
    target2 REAL NOT NULL,
    quantity REAL NOT NULL,
    remaining_quantity REAL NOT NULL,
    realised_quantity REAL NOT NULL,
    realised_pnl REAL NOT NULL DEFAULT 0,
    last_price REAL,
    exit_price REAL,
    reason TEXT NOT NULL
    ,progression_stage TEXT NOT NULL DEFAULT 'ENTRY_PENDING'
);
CREATE INDEX IF NOT EXISTS idx_v2_positions_symbol_state
ON v2_positions(symbol, state);

CREATE TABLE IF NOT EXISTS v2_position_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    price REAL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_id) REFERENCES v2_positions(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_v2_events_trade
ON v2_position_events(trade_id, event_id);

CREATE TABLE IF NOT EXISTS v2_portfolio_snapshots (
    portfolio_date TEXT PRIMARY KEY,
    capital_base REAL NOT NULL,
    committed_capital REAL NOT NULL,
    market_value REAL NOT NULL,
    realised_pnl REAL NOT NULL,
    unrealised_pnl REAL NOT NULL,
    total_pnl REAL NOT NULL,
    portfolio_return_pct REAL NOT NULL,
    initial_risk REAL NOT NULL,
    open_risk_to_stops REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    pending_setups INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v2_watchlist_memory (
    symbol TEXT NOT NULL,
    horizon TEXT NOT NULL,
    first_seen_date TEXT NOT NULL,
    last_seen_date TEXT NOT NULL,
    last_score REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL,
    PRIMARY KEY(symbol, horizon)
);

CREATE TABLE IF NOT EXISTS v2_opportunity_state (
    symbol TEXT PRIMARY KEY,
    progression_stage TEXT NOT NULL,
    opportunity_classification TEXT NOT NULL,
    first_seen_date TEXT NOT NULL,
    last_seen_date TEXT NOT NULL,
    last_score REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    previously_exited INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS v2_candidate_history (
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    progression_stage TEXT NOT NULL,
    opportunity_classification TEXT NOT NULL,
    scanner_rank INTEGER,
    score REAL NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(symbol, trade_date)
);
"""


class PortfolioStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(v2_positions)")}
            if "initial_stop" not in columns:
                conn.execute("ALTER TABLE v2_positions ADD COLUMN initial_stop REAL")
                conn.execute("UPDATE v2_positions SET initial_stop=stop WHERE initial_stop IS NULL")
            if "realised_pnl" not in columns:
                conn.execute("ALTER TABLE v2_positions ADD COLUMN realised_pnl REAL NOT NULL DEFAULT 0")
            if "progression_stage" not in columns:
                conn.execute(
                    "ALTER TABLE v2_positions ADD COLUMN progression_stage TEXT NOT NULL DEFAULT 'ENTRY_PENDING'"
                )

    def save_position(
        self, position: Position, event_type: str, previous_state: TradeState | None = None, price: float | None = None
    ) -> None:
        payload = asdict(position)
        payload["state"] = position.state.value
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO v2_positions (
                    trade_id,symbol,horizon,state,created_date,updated_date,
                    entry,initial_stop,stop,target1,target2,quantity,remaining_quantity,
                    realised_quantity,realised_pnl,last_price,exit_price,reason,progression_stage
                ) VALUES (
                    :trade_id,:symbol,:horizon,:state,:created_date,:updated_date,
                    :entry,:initial_stop,:stop,:target1,:target2,:quantity,:remaining_quantity,
                    :realised_quantity,:realised_pnl,:last_price,:exit_price,:reason,:progression_stage)
                   ON CONFLICT(trade_id) DO UPDATE SET
                    horizon=excluded.horizon, state=excluded.state,
                    updated_date=excluded.updated_date,
                    initial_stop=COALESCE(v2_positions.initial_stop, excluded.initial_stop),
                    stop=excluded.stop, remaining_quantity=excluded.remaining_quantity,
                    realised_quantity=excluded.realised_quantity,
                    realised_pnl=excluded.realised_pnl,
                    last_price=excluded.last_price, exit_price=excluded.exit_price,
                    reason=excluded.reason, progression_stage=excluded.progression_stage""",
                payload,
            )
            conn.execute(
                """INSERT INTO v2_position_events
                   (trade_id,event_date,event_type,from_state,to_state,price,reason,payload_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    position.trade_id,
                    position.updated_date,
                    event_type,
                    previous_state.value if previous_state else None,
                    position.state.value,
                    price,
                    position.reason,
                    json.dumps(payload, default=str),
                ),
            )

    def get_position(self, trade_id: str) -> Position | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM v2_positions WHERE trade_id=?", (trade_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["state"] = TradeState(data["state"])
        return Position(**data)

    def open_positions(self) -> list[Position]:
        closed = (TradeState.CLOSED.value, TradeState.CANCELLED.value)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM v2_positions WHERE state NOT IN (?,?) ORDER BY created_date, trade_id",
                closed,
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["state"] = TradeState(data["state"])
            result.append(Position(**data))
        return result

    def positions_for_daily_report(self, trade_date: str) -> list[Position]:
        """All active positions plus any closed/cancelled on this completed session."""
        closed = (TradeState.CLOSED.value, TradeState.CANCELLED.value)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM v2_positions
                   WHERE state NOT IN (?, ?) OR updated_date=?
                   ORDER BY created_date, trade_id""",
                (*closed, trade_date),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["state"] = TradeState(data["state"])
            result.append(Position(**data))
        return result

    def all_positions(self) -> list[Position]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM v2_positions ORDER BY created_date, trade_id").fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["state"] = TradeState(data["state"])
            result.append(Position(**data))
        return result

    def save_portfolio_snapshot(self, snapshot: object) -> None:
        from dataclasses import asdict

        payload = asdict(snapshot)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO v2_portfolio_snapshots (
                    portfolio_date,capital_base,committed_capital,market_value,realised_pnl,
                    unrealised_pnl,total_pnl,portfolio_return_pct,initial_risk,open_risk_to_stops,
                    open_positions,pending_setups,snapshot_json
                ) VALUES (
                    :portfolio_date,:capital_base,:committed_capital,:market_value,:realised_pnl,
                    :unrealised_pnl,:total_pnl,:portfolio_return_pct,:initial_risk,:open_risk_to_stops,
                    :open_positions,:pending_setups,:snapshot_json
                ) ON CONFLICT(portfolio_date) DO UPDATE SET
                    committed_capital=excluded.committed_capital, market_value=excluded.market_value,
                    realised_pnl=excluded.realised_pnl, unrealised_pnl=excluded.unrealised_pnl,
                    total_pnl=excluded.total_pnl, portfolio_return_pct=excluded.portfolio_return_pct,
                    initial_risk=excluded.initial_risk, open_risk_to_stops=excluded.open_risk_to_stops,
                    open_positions=excluded.open_positions, pending_setups=excluded.pending_setups,
                    snapshot_json=excluded.snapshot_json""",
                {**payload, "snapshot_json": json.dumps(payload)},
            )

    def latest_portfolio_snapshot(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM v2_portfolio_snapshots ORDER BY portfolio_date DESC LIMIT 1").fetchone()

    def remember_candidate(
        self, symbol: str, horizon: str, trade_date: str, score: float, reason: str = "selected_candidate"
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO v2_watchlist_memory
                   (symbol,horizon,first_seen_date,last_seen_date,last_score,active,reason)
                   VALUES (?,?,?,?,?,1,?)
                   ON CONFLICT(symbol,horizon) DO UPDATE SET
                    last_seen_date=excluded.last_seen_date,
                    last_score=excluded.last_score,
                    active=1,
                    reason=excluded.reason""",
                (symbol, horizon, trade_date, trade_date, score, reason),
            )

    def deactivate_watch(self, symbol: str, horizon: str, reason: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE v2_watchlist_memory SET active=0, reason=? WHERE symbol=? AND horizon=?",
                (reason, symbol, horizon),
            )

    def opportunity_state(self, symbol: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM v2_opportunity_state WHERE symbol=?", (symbol,)).fetchone()

    def remember_opportunity(self, candidate: object, scanner_rank: int | None = None) -> None:
        payload = candidate.to_dict()
        symbol = str(payload["symbol"])
        trade_date = str(payload["trade_date"])
        stage = str(payload["progression_stage"])
        classification = str(payload["opportunity_classification"])
        score = float(payload["score"])
        active = int(stage != "EXITED")
        with self.connect() as conn:
            prior = conn.execute("SELECT * FROM v2_opportunity_state WHERE symbol=?", (symbol,)).fetchone()
            first_seen = prior["first_seen_date"] if prior else trade_date
            previously_exited = int(
                (prior and (prior["previously_exited"] or not prior["active"])) or stage == "EXITED"
            )
            conn.execute(
                """INSERT INTO v2_opportunity_state
                   (symbol,progression_stage,opportunity_classification,first_seen_date,last_seen_date,last_score,active,previously_exited)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET
                    progression_stage=excluded.progression_stage,
                    opportunity_classification=excluded.opportunity_classification,
                    last_seen_date=excluded.last_seen_date,last_score=excluded.last_score,
                    active=excluded.active,previously_exited=excluded.previously_exited""",
                (symbol, stage, classification, first_seen, trade_date, score, active, previously_exited),
            )
            conn.execute(
                """INSERT INTO v2_candidate_history
                   (symbol,trade_date,progression_stage,opportunity_classification,scanner_rank,score,payload_json)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(symbol,trade_date) DO UPDATE SET
                    progression_stage=excluded.progression_stage,
                    opportunity_classification=excluded.opportunity_classification,
                    scanner_rank=excluded.scanner_rank,score=excluded.score,payload_json=excluded.payload_json""",
                (symbol, trade_date, stage, classification, scanner_rank, score, json.dumps(payload, default=str)),
            )
