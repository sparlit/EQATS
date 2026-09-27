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


"""Read-only database access for NSE Scanner V2."""

import json
import sqlite3
from pathlib import Path

import pandas as pd


class V2Database:
    def __init__(self, path: str | Path = "nse_scanner.db") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_v3_schema(self) -> None:
        """Apply additive V3 fields/tables idempotently before a daily run."""
        with self.connect() as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "symbol_master_v2" not in names:
                conn.execute("""CREATE TABLE symbol_master_v2 (
                    symbol TEXT PRIMARY KEY, isin TEXT, company_name TEXT, series TEXT,
                    sector TEXT, industry TEXT, listing_date TEXT, delisting_date TEXT,
                    active INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    market_cap_cr REAL, market_cap_as_of TEXT, market_cap_source TEXT)""")
                names.add("symbol_master_v2")
            if "symbol_master_v2" in names:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(symbol_master_v2)")}
                if "market_cap_cr" not in columns:
                    conn.execute("ALTER TABLE symbol_master_v2 ADD COLUMN market_cap_cr REAL")
                if "market_cap_as_of" not in columns:
                    conn.execute("ALTER TABLE symbol_master_v2 ADD COLUMN market_cap_as_of DATE")
                if "market_cap_source" not in columns:
                    conn.execute("ALTER TABLE symbol_master_v2 ADD COLUMN market_cap_source TEXT")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS regulatory_restrictions_v2 (
                    symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
                    restriction_type TEXT NOT NULL, reason TEXT, source TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, trade_date, restriction_type));
                CREATE TABLE IF NOT EXISTS v3_eligibility_audit (
                    symbol TEXT NOT NULL, trade_date TEXT NOT NULL, eligible INTEGER NOT NULL,
                    stage TEXT NOT NULL, reason_code TEXT NOT NULL, actual_value TEXT,
                    required_value TEXT, metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, trade_date));
                CREATE TABLE IF NOT EXISTS fundamental_snapshots_v3 (
                    symbol TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    revenue_growth_pct REAL NOT NULL, profit_growth_pct REAL NOT NULL,
                    roe_pct REAL NOT NULL, debt_to_equity REAL NOT NULL,
                    operating_cash_flow_positive INTEGER NOT NULL,
                    promoter_pledge_pct REAL NOT NULL, governance_flag INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT 'CONTROLLED_IMPORT',
                    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, as_of_date));
                CREATE TABLE IF NOT EXISTS corporate_filings_v3 (
                    filing_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                    filing_type TEXT NOT NULL, period_end_date TEXT,
                    available_date TEXT NOT NULL, source_url TEXT, raw_path TEXT,
                    parser_version TEXT, loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS shares_outstanding_v3 (
                    symbol TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    available_date TEXT NOT NULL, shares_outstanding REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'NSE_SHAREHOLDING', filing_id TEXT,
                    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, as_of_date, available_date));
                CREATE TABLE IF NOT EXISTS market_cap_snapshots_v3 (
                    symbol TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    available_date TEXT NOT NULL, market_cap_cr REAL NOT NULL,
                    source TEXT NOT NULL, filing_id TEXT,
                    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, as_of_date, source));
                CREATE TABLE IF NOT EXISTS promoter_pledge_v3 (
                    symbol TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    available_date TEXT NOT NULL, pledge_pct REAL NOT NULL,
                    event_type TEXT NOT NULL DEFAULT 'SNAPSHOT', source TEXT NOT NULL,
                    filing_id TEXT, loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, as_of_date, event_type));
                CREATE TABLE IF NOT EXISTS governance_events_v3 (
                    symbol TEXT NOT NULL, event_date TEXT NOT NULL,
                    available_date TEXT NOT NULL, event_type TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK(severity IN ('REVIEW','SEVERE')),
                    summary TEXT, source TEXT NOT NULL, filing_id TEXT,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, event_date, event_type));
                CREATE TABLE IF NOT EXISTS shareholding_patterns_v3 (
                    symbol TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    available_date TEXT NOT NULL, shares_outstanding REAL NOT NULL,
                    promoter_holding_pct REAL, public_holding_pct REAL,
                    source TEXT NOT NULL, filing_id TEXT,
                    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, as_of_date));
                CREATE TABLE IF NOT EXISTS corporate_actions_v3 (
                    symbol TEXT NOT NULL, ex_date TEXT NOT NULL,
                    available_date TEXT NOT NULL, action_type TEXT NOT NULL,
                    ratio_from REAL, ratio_to REAL, description TEXT,
                    source TEXT NOT NULL, filing_id TEXT,
                    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, ex_date, action_type));
                CREATE TABLE IF NOT EXISTS corporate_dataset_health_v3 (
                    dataset TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    status TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
                    detail TEXT, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(dataset, as_of_date));
            """)

    def load_fundamental_gates(self, trade_date: str, max_age_days: int = 120) -> dict[str, bool]:
        from .fundamentals import FundamentalSnapshot, evaluate_fundamentals

        with self.connect() as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "fundamental_snapshots_v3" not in names:
                return {}
            rows = conn.execute(
                """SELECT f.* FROM fundamental_snapshots_v3 f
                JOIN (SELECT symbol, MAX(as_of_date) AS latest FROM fundamental_snapshots_v3
                      WHERE as_of_date<=? GROUP BY symbol) latest
                ON f.symbol=latest.symbol AND f.as_of_date=latest.latest""",
                (trade_date,),
            ).fetchall()
        gates = {}
        for row in rows:
            if (pd.Timestamp(trade_date) - pd.Timestamp(row["as_of_date"])).days > max_age_days:
                continue
            snapshot = FundamentalSnapshot(
                symbol=row["symbol"],
                as_of_date=row["as_of_date"],
                revenue_growth_pct=row["revenue_growth_pct"],
                profit_growth_pct=row["profit_growth_pct"],
                roe_pct=row["roe_pct"],
                debt_to_equity=row["debt_to_equity"],
                operating_cash_flow_positive=bool(row["operating_cash_flow_positive"]),
                promoter_pledge_pct=row["promoter_pledge_pct"],
                governance_flag=bool(row["governance_flag"]),
            )
            gates[str(row["symbol"])] = evaluate_fundamentals(snapshot).passed
        return gates

    def price_table(self, conn: sqlite3.Connection) -> str:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "daily_prices_v2" in names:
            return "daily_prices_v2"
        if "daily_prices" in names:
            return "daily_prices"
        msg = "No supported daily price table found"
        raise RuntimeError(msg)

    def load_prices(self, end_date: str | None = None, min_sessions: int = 0) -> pd.DataFrame:
        with self.connect() as conn:
            table = self.price_table(conn)
            date_col = "trade_date" if table == "daily_prices_v2" else "date"
            available = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            optional = [
                column
                for column in ("turnover_lacs", "delivery_qty", "delivery_pct", "quality_status")
                if column in available
            ]
            selected = ["symbol", f"{date_col} AS trade_date", "open", "high", "low", "close", "volume", *optional]
            query = f"SELECT {', '.join(selected)} FROM {table}"
            params: list[object] = []
            if end_date:
                query += f" WHERE {date_col} <= ?"
                params.append(end_date)
            query += " ORDER BY symbol, trade_date"
            frame = pd.read_sql_query(query, conn, params=params, parse_dates=["trade_date"])
        if min_sessions:
            counts = frame.groupby("symbol")["trade_date"].nunique()
            frame = frame[frame["symbol"].isin(counts[counts >= min_sessions].index)]
        return frame

    def load_symbol_master(self, as_of_date: str | None = None) -> pd.DataFrame:
        """Return V2 metadata plus the latest point-in-time NSE ownership record."""
        with self.connect() as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "symbol_master_v2" not in names:
                return pd.DataFrame(
                    columns=["symbol", "series", "active", "market_cap_cr", "market_cap_as_of", "market_cap_source"]
                )
            available = {row[1] for row in conn.execute("PRAGMA table_info(symbol_master_v2)")}
            columns = [
                column
                for column in (
                    "symbol",
                    "series",
                    "active",
                    "delisting_date",
                    "market_cap_cr",
                    "market_cap_as_of",
                    "market_cap_source",
                )
                if column in available
            ]
            if "shareholding_patterns_v3" not in names:
                return pd.read_sql_query(f"SELECT {', '.join(columns)} FROM symbol_master_v2", conn)
            cutoff = as_of_date or "9999-12-31"
            return pd.read_sql_query(
                f"""
                SELECT m.{", m.".join(columns)},
                       s.promoter_holding_pct,
                       s.as_of_date AS promoter_holding_as_of,
                       s.available_date AS promoter_holding_available_date,
                       s.source AS promoter_holding_source,
                       s.filing_id AS promoter_holding_filing_id,
                       a.action_type AS corporate_action_type,
                       a.ex_date AS corporate_action_ex_date,
                       a.available_date AS corporate_action_available_date,
                       a.filing_id AS corporate_action_filing_id
                FROM symbol_master_v2 m
                LEFT JOIN shareholding_patterns_v3 s ON s.rowid = (
                    SELECT candidate.rowid FROM shareholding_patterns_v3 candidate
                    WHERE candidate.symbol=m.symbol AND candidate.available_date<=?
                    ORDER BY candidate.available_date DESC, candidate.as_of_date DESC,
                             candidate.filing_id DESC
                    LIMIT 1
                )
                LEFT JOIN corporate_actions_v3 a ON a.rowid = (
                    SELECT candidate.rowid FROM corporate_actions_v3 candidate
                    WHERE candidate.symbol=m.symbol AND candidate.available_date<=?
                      AND candidate.ex_date BETWEEN date(?, '-5 days') AND date(?, '+14 days')
                      AND (upper(candidate.action_type) LIKE '%BONUS%'
                           OR upper(candidate.action_type) LIKE '%SPLIT%'
                           OR upper(candidate.action_type) LIKE '%RIGHT%'
                           OR upper(candidate.action_type) LIKE '%MERGER%'
                           OR upper(candidate.action_type) LIKE '%AMALGAMATION%'
                           OR upper(candidate.action_type) LIKE '%DEMERGER%'
                           OR upper(candidate.action_type) LIKE '%BUYBACK%'
                           OR upper(candidate.action_type) LIKE '%DELIST%'
                           OR upper(candidate.action_type) LIKE '%REDUCTION%')
                    ORDER BY candidate.ex_date ASC, candidate.available_date DESC
                    LIMIT 1
                )
            """,
                conn,
                params=[cutoff, cutoff, cutoff, cutoff],
            )

    def load_lifecycle_registry(self) -> dict[str, dict]:
        """Load the git-backed terminal-event registry for disposable runners."""
        path = Path("corporate_data/normalized/security_lifecycle_events.csv")
        if not path.exists():
            return {}
        frame = pd.read_csv(path, dtype=str).fillna("")
        return {str(row["symbol"]).upper(): row.to_dict() for _, row in frame.iterrows()}

    def load_restricted_symbols(self, trade_date: str) -> dict[str, str]:
        """Load dated regulatory exclusions when a compatible table is available."""
        with self.connect() as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "regulatory_restrictions_v2" in names:
                rows = conn.execute(
                    """SELECT symbol, restriction_type, reason
                       FROM regulatory_restrictions_v2
                       WHERE trade_date=? AND active=1""",
                    (trade_date,),
                ).fetchall()
                if rows:
                    return {
                        str(row["symbol"]): f"{row['restriction_type']}: {row['reason'] or 'restricted'}"
                        for row in rows
                    }
            if "blacklist" not in names:
                return {}
            columns = {row[1] for row in conn.execute("PRAGMA table_info(blacklist)")}
            date_column = "trade_date" if "trade_date" in columns else "date" if "date" in columns else None
            reason_column = "reason" if "reason" in columns else None
            if not date_column:
                return {}
            reason_sql = reason_column or "'REGULATORY_RESTRICTION'"
            rows = conn.execute(
                f"SELECT symbol, {reason_sql} AS reason FROM blacklist WHERE {date_column}=?",
                (trade_date,),
            ).fetchall()
            return {str(row["symbol"]): str(row["reason"] or "REGULATORY_RESTRICTION") for row in rows}

    def save_eligibility_audit(self, trade_date: str, results: dict[str, object]) -> None:
        with self.connect() as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "v3_eligibility_audit" not in names:
                conn.execute("""CREATE TABLE v3_eligibility_audit (
                    symbol TEXT NOT NULL, trade_date TEXT NOT NULL, eligible INTEGER NOT NULL,
                    stage TEXT NOT NULL, reason_code TEXT NOT NULL, actual_value TEXT,
                    required_value TEXT, metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(symbol, trade_date))""")
            rows = []
            for symbol, result in results.items():
                payload = result.to_dict()
                rows.append(
                    (
                        symbol,
                        trade_date,
                        int(payload["eligible"]),
                        payload["stage"],
                        payload["reason_code"],
                        None if payload["actual_value"] is None else str(payload["actual_value"]),
                        None if payload["required_value"] is None else str(payload["required_value"]),
                        json.dumps(payload.get("metrics") or {}, default=str),
                    )
                )
            conn.executemany(
                """INSERT INTO v3_eligibility_audit
                (symbol,trade_date,eligible,stage,reason_code,actual_value,required_value,metrics_json)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,trade_date) DO UPDATE SET eligible=excluded.eligible,
                stage=excluded.stage,reason_code=excluded.reason_code,actual_value=excluded.actual_value,
                required_value=excluded.required_value,metrics_json=excluded.metrics_json""",
                rows,
            )

    def load_indices(self, end_date: str | None = None) -> pd.DataFrame:
        with self.connect() as conn:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "index_perf" not in names:
                return pd.DataFrame(columns=["index_name", "trade_date", "open", "high", "low", "close"])
            query = "SELECT index_name, date AS trade_date, open, high, low, close FROM index_perf"
            params: list[object] = []
            if end_date:
                query += " WHERE date <= ?"
                params.append(end_date)
            query += " ORDER BY index_name, date"
            return pd.read_sql_query(query, conn, params=params, parse_dates=["trade_date"])
