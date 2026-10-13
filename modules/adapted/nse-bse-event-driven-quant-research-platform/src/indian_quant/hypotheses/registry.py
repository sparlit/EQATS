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


"""Hypothesis registry — maps names to classes and manages lifecycle."""


import json
import logging
from typing import TYPE_CHECKING

import sqlalchemy as sa

from indian_quant.config.connections import get_engine

if TYPE_CHECKING:
    from indian_quant.hypotheses.base import BaseHypothesis

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BaseHypothesis]] = {}


def register_hypothesis(cls: type[BaseHypothesis]) -> type[BaseHypothesis]:
    """Decorator to register a hypothesis class."""
    _REGISTRY[cls.name] = cls
    return cls


def get_hypothesis(name: str) -> BaseHypothesis:
    """Instantiate a registered hypothesis by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown hypothesis: {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]()


def list_hypotheses() -> list[str]:
    return list(_REGISTRY.keys())


class HypothesisRegistry:
    """Manages hypothesis persistence and lifecycle in PostgreSQL."""

    def __init__(self, engine=None):
        self._engine = engine or get_engine()

    # ── CRUD ──

    def create(
        self,
        name: str,
        description: str = "",
        signal_logic: dict | None = None,
        max_positions: int = 7,
    ) -> int:
        values = {
            "name": name,
            "description": description,
            "signal_logic": json.dumps(signal_logic or {}),
            "max_positions": max_positions,
        }
        sql = sa.text("""
            INSERT INTO hypotheses (name, description, signal_logic, max_positions)
            VALUES (:name, :description, CAST(:signal_logic AS jsonb), :max_positions)
            ON CONFLICT (name) DO UPDATE SET
                description = EXCLUDED.description,
                signal_logic = EXCLUDED.signal_logic,
                max_positions = EXCLUDED.max_positions
            RETURNING id
        """)
        with self._engine.begin() as conn:
            return conn.execute(sql, values).scalar()

    def get(self, name: str) -> dict | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(sa.text("SELECT * FROM hypotheses WHERE name = :name"), {"name": name})
                .mappings()
                .fetchone()
            )
            return dict(row) if row else None

    def get_by_id(self, hypo_id: int) -> dict | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(sa.text("SELECT * FROM hypotheses WHERE id = :id"), {"id": hypo_id})
                .mappings()
                .fetchone()
            )
            return dict(row) if row else None

    def list_all(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(sa.text("SELECT * FROM hypotheses ORDER BY id")).mappings().fetchall()
            )
            return [dict(r) for r in rows]

    def deactivate(self, name: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE hypotheses SET is_active = FALSE WHERE name = :name"),
                {"name": name},
            )

    # ── Stocks ──

    def add_stock(
        self, hypothesis_id: int, symbol: str, exchange: str = "NSE", added_by: str = "system"
    ) -> int:
        values = {
            "hypothesis_id": hypothesis_id,
            "symbol": symbol.upper(),
            "exchange": exchange,
            "added_by": added_by,
        }
        sql = sa.text("""
            INSERT INTO hypothesis_stocks (hypothesis_id, symbol, exchange, added_by)
            VALUES (:hypothesis_id, :symbol, :exchange, :added_by)
            ON CONFLICT (hypothesis_id, symbol) DO NOTHING
            RETURNING id
        """)
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            return result.scalar() or 0

    def add_stocks(
        self,
        hypothesis_id: int,
        symbols: list[str],
        exchange: str = "NSE",
        added_by: str = "system",
    ) -> int:
        count = 0
        for sym in symbols:
            rid = self.add_stock(hypothesis_id, sym, exchange, added_by)
            if rid:
                count += 1
        return count

    def remove_stock(self, hypothesis_id: int, symbol: str, reason: str = "manual") -> bool:
        values = {"hypothesis_id": hypothesis_id, "symbol": symbol.upper(), "reason": reason}
        sql = sa.text("""
            UPDATE hypothesis_stocks
            SET removed_at = NOW(), removal_reason = :reason
            WHERE hypothesis_id = :hypothesis_id AND symbol = :symbol AND removed_at IS NULL
        """)
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            return result.rowcount > 0

    def list_stocks(self, hypothesis_id: int, active_only: bool = True) -> list[dict]:
        cond = "WHERE hypothesis_id = :hid"
        if active_only:
            cond += " AND removed_at IS NULL"
        sql = sa.text(f"SELECT * FROM hypothesis_stocks {cond} ORDER BY added_at DESC")
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"hid": hypothesis_id}).mappings().fetchall()
            return [dict(r) for r in rows]

    def stock_count(self, hypothesis_id: int, active_only: bool = True) -> int:
        cond = "WHERE hypothesis_id = :hid"
        if active_only:
            cond += " AND removed_at IS NULL"
        sql = sa.text(f"SELECT COUNT(*) FROM hypothesis_stocks {cond}")
        with self._engine.connect() as conn:
            return conn.execute(sql, {"hid": hypothesis_id}).scalar()

    def get_active_symbols(self, hypothesis_id: int) -> list[str]:
        sql = sa.text("""
            SELECT symbol FROM hypothesis_stocks
            WHERE hypothesis_id = :hid AND removed_at IS NULL
            ORDER BY symbol
        """)
        with self._engine.connect() as conn:
            return [r[0] for r in conn.execute(sql, {"hid": hypothesis_id}).fetchall()]

    # ── Signals ──

    def record_signal(
        self,
        hypothesis_id: int,
        symbol: str,
        signal_date: str,
        signal_type: str,
        strength: float,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        **kwargs,
    ) -> int:
        values = {
            "hypothesis_id": hypothesis_id,
            "symbol": symbol.upper(),
            "signal_date": signal_date,
            "signal_type": signal_type,
            "strength": strength,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "close": kwargs.get("close", 0.0),
            "deliv_z": kwargs.get("deliv_z", 0.0),
            "vol_z": kwargs.get("vol_z", 0.0),
            "rsi": kwargs.get("rsi", 0.0),
            "macd_hist": kwargs.get("macd_hist", 0.0),
            "turnover": kwargs.get("turnover", 0.0),
            "market_cap_cr": kwargs.get("market_cap_cr", 0.0),
            "notes": kwargs.get("notes", ""),
        }
        cols = ", ".join(values.keys())
        phs = ", ".join(f":{k}" for k in values)
        sql = sa.text(f"INSERT INTO hypothesis_signals ({cols}) VALUES ({phs}) RETURNING id")
        with self._engine.begin() as conn:
            return conn.execute(sql, values).scalar()

    def get_signals(
        self, hypothesis_id: int, signal_date: str | None = None, limit: int = 100
    ) -> list[dict]:
        cond = "WHERE hypothesis_id = :hid"
        params: dict = {"hid": hypothesis_id, "lim": limit}
        if signal_date:
            cond += " AND signal_date = :sdate"
            params["sdate"] = signal_date
        sql = sa.text(f"""
            SELECT * FROM hypothesis_signals {cond}
            ORDER BY strength DESC, signal_date DESC LIMIT :lim
        """)
        with self._engine.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).mappings().fetchall()]

    def latest_signals(self, hypothesis_id: int, limit: int = 7) -> list[dict]:
        sql = sa.text("""
            SELECT * FROM hypothesis_signals
            WHERE hypothesis_id = :hid
            AND signal_date = (SELECT MAX(signal_date) FROM hypothesis_signals WHERE hypothesis_id = :hid2)
            ORDER BY strength DESC
            LIMIT :lim
        """)
        with self._engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    sql, {"hid": hypothesis_id, "hid2": hypothesis_id, "lim": limit}
                )
                .mappings()
                .fetchall()
            ]

    # ── Trades ──

    def open_trade(
        self,
        hypothesis_id: int,
        symbol: str,
        entry_date: str,
        entry_price: float,
        qty: int,
        signal_id: int | None = None,
        stop_pct: float = 0.07,
        horizon_days: int = 10,
        notes: str = "",
        exchange: str = "NSE",
    ) -> int:
        entry_value = entry_price * qty
        values = {
            "hypothesis_id": hypothesis_id,
            "signal_id": signal_id,
            "symbol": symbol.upper(),
            "exchange": exchange,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "qty": qty,
            "entry_value": entry_value,
            "stop_pct": stop_pct,
            "horizon_days": horizon_days,
            "notes": notes,
        }
        sql = sa.text("""
            INSERT INTO hypothesis_trades
                (hypothesis_id, signal_id, symbol, exchange, entry_date, entry_price,
                 qty, entry_value, stop_pct, horizon_days, notes, status)
            VALUES (:hypothesis_id, :signal_id, :symbol, :exchange, :entry_date, :entry_price,
                    :qty, :entry_value, :stop_pct, :horizon_days, :notes, 'OPEN')
            RETURNING id
        """)
        with self._engine.begin() as conn:
            return conn.execute(sql, values).scalar()

    def close_trade(
        self,
        trade_id: int,
        exit_date: str,
        exit_price: float,
        exit_reason: str = "HORIZON",
        notes: str = "",
    ) -> dict:
        with self._engine.connect() as conn:
            # Try paper_signals first (primary source of truth)
            trade = (
                conn.execute(
                    sa.text("SELECT * FROM paper_signals WHERE id = :id"), {"id": trade_id}
                )
                .mappings()
                .fetchone()
            )
            if trade:
                return self._close_paper_signal(
                    conn, trade, exit_date, exit_price, exit_reason, notes
                )
            # Fall back to hypothesis_trades (audit trail)
            trade = (
                conn.execute(
                    sa.text("SELECT * FROM hypothesis_trades WHERE id = :id"), {"id": trade_id}
                )
                .mappings()
                .fetchone()
            )
            if trade:
                return self._close_hypothesis_trade(
                    conn, trade, exit_date, exit_price, exit_reason, notes
                )
        raise ValueError(f"Trade {trade_id} not found")

    def _close_paper_signal(self, conn, trade, exit_date, exit_price, exit_reason, notes) -> dict:
        t = dict(trade)
        gross_bps = ((exit_price / t["close_at_signal"]) - 1) * 10_000
        total_cost = 214.0
        net_bps = gross_bps - total_cost
        return_pct = gross_bps / 100.0
        from datetime import datetime as _dt

        try:
            entry_dt = _dt.strptime(str(t["entry_date"])[:10], "%Y-%m-%d").date()
            exit_dt = _dt.strptime(str(exit_date)[:10], "%Y-%m-%d").date()
            days_held = (exit_dt - entry_dt).days
        except Exception:
            days_held = 0
        values = {
            "id": t["id"],
            "exit_date": str(exit_date),
            "exit_close": exit_price,
            "exit_reason": exit_reason,
            "realized_net_bps": net_bps,
            "return_pct": return_pct,
            "return_bps": gross_bps,
            "days_held": days_held,
            "status": "SETTLED",
            "note": notes or f"Auto-settled: {exit_reason}",
        }
        sql = sa.text("""
            UPDATE paper_signals SET
                exit_date = :exit_date, exit_close = :exit_close,
                exit_reason = :exit_reason, realized_net_bps = :realized_net_bps,
                return_pct = :return_pct, return_bps = :return_bps,
                days_held = :days_held, status = 'SETTLED',
                note = :note
            WHERE id = :id RETURNING *
        """)
        with self._engine.begin() as cn:
            result = cn.execute(sql, values)
            row = result.mappings().fetchone()
            closed = dict(row) if row else {}
        # Sync journal exit (best-effort: never break settling on journal errors)
        if closed:
            try:
                from indian_quant.storage.pg_metadata import PgMetadataStore

                PgMetadataStore(self._engine).journal_record_on_exit(
                    paper_trade_id=t["id"],
                    exit_date=str(exit_date)[:10],
                    exit_price=float(exit_price),
                    exit_reason=exit_reason,
                    exit_rationale=notes or f"Auto-settled: {exit_reason}",
                    days_held=days_held,
                    return_pct=return_pct,
                    return_bps=gross_bps,
                    net_bps=net_bps,
                )
            except Exception as e:
                log.warning(f"journal exit sync failed for paper id {t['id']}: {e}")
        return closed

    def _close_hypothesis_trade(
        self, conn, trade, exit_date, exit_price, exit_reason, notes
    ) -> dict:
        t = dict(trade)
        gross_bps = ((exit_price / t["entry_price"]) - 1) * 10_000
        total_cost = 107.0
        net_bps = gross_bps - total_cost
        return_pct = gross_bps / 100.0
        from datetime import datetime as _dt

        try:
            entry_dt = _dt.strptime(str(t["entry_date"])[:10], "%Y-%m-%d").date()
            exit_dt = _dt.strptime(str(exit_date)[:10], "%Y-%m-%d").date()
            days_held = (exit_dt - entry_dt).days
        except Exception:
            days_held = 0
        values = {
            "id": t["id"],
            "exit_date": str(exit_date),
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "gross_bps": gross_bps,
            "net_bps": net_bps,
            "return_pct": return_pct,
            "days_held": days_held,
            "notes": notes or f"Auto-settled: {exit_reason}",
        }
        sql = sa.text("""
            UPDATE hypothesis_trades SET
                exit_date = :exit_date, exit_price = :exit_price,
                exit_reason = :exit_reason, gross_bps = :gross_bps,
                net_bps = :net_bps, return_pct = :return_pct,
                days_held = :days_held, status = 'SETTLED',
                exit_value = :exit_price * qty,
                notes = :notes
            WHERE id = :id RETURNING *
        """)
        with self._engine.begin() as cn:
            result = cn.execute(sql, values)
            row = result.mappings().fetchone()
            return dict(row) if row else {}

    def cancel_trade(self, trade_id: int, reason: str = "manual") -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.text(
                    "UPDATE hypothesis_trades SET status = 'CANCELLED', exit_reason = :reason WHERE id = :id AND status = 'OPEN'"
                ),
                {"id": trade_id, "reason": reason},
            )
            return result.rowcount > 0

    def open_trades(self, hypothesis_id: int | None = None) -> list[dict]:
        cond = "WHERE status = 'OPEN'"
        params: dict = {}
        if hypothesis_id is not None:
            cond += " AND hypothesis_id = :hid"
            params["hid"] = hypothesis_id
        sql = sa.text(f"""
            SELECT *, close_at_signal as entry_price, position_value as entry_value
            FROM paper_signals {cond} ORDER BY entry_date DESC
        """)
        with self._engine.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).mappings().fetchall()]

    def settled_trades(self, hypothesis_id: int | None = None, limit: int = 100) -> list[dict]:
        cond = "WHERE status = 'SETTLED'"
        params: dict = {"lim": limit}
        if hypothesis_id is not None:
            cond += " AND hypothesis_id = :hid"
            params["hid"] = hypothesis_id
        sql = sa.text(f"""
            SELECT *, close_at_signal as entry_price, position_value as entry_value,
                   exit_close as exit_price,
                   COALESCE(realized_net_bps, 0) as net_bps,
                   COALESCE(return_bps, 0) as gross_bps
            FROM paper_signals {cond}
            ORDER BY exit_date DESC LIMIT :lim
        """)
        with self._engine.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).mappings().fetchall()]

    def trade_summary(self, hypothesis_id: int) -> dict:
        sql = sa.text("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open,
                SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END) as settled,
                SUM(CASE WHEN status = 'SETTLED' AND realized_net_bps > 0 THEN 1 ELSE 0 END) as wins,
                AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps,
                AVG(CASE WHEN status = 'SETTLED' THEN return_pct END) as avg_return_pct,
                AVG(CASE WHEN status = 'SETTLED' THEN days_held END) as avg_days_held,
                SUM(CASE WHEN status = 'OPEN' THEN position_value ELSE 0 END) as capital_deployed,
                SUM(CASE WHEN status = 'SETTLED' THEN return_pct ELSE 0 END) as total_pnl
            FROM paper_signals WHERE hypothesis_id = :hid
        """)
        with self._engine.connect() as conn:
            r = conn.execute(sql, {"hid": hypothesis_id}).mappings().fetchone()
            d = dict(r) if r else {}
            if d.get("settled") and d.get("wins") is not None:
                d["win_rate"] = d["wins"] / d["settled"] * 100
            else:
                d["win_rate"] = 0.0
            return d

    def stock_trades(self, symbol: str, hypothesis_id: int | None = None) -> list[dict]:
        cond = "WHERE symbol = :sym"
        params: dict = {"sym": symbol.upper()}
        if hypothesis_id is not None:
            cond += " AND hypothesis_id = :hid"
            params["hid"] = hypothesis_id
        sql = sa.text(f"SELECT * FROM hypothesis_trades {cond} ORDER BY entry_date DESC")
        with self._engine.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).mappings().fetchall()]
