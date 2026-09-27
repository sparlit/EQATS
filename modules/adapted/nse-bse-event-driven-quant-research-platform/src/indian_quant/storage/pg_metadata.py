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


"""PostgreSQL-backed metadata store for paper signals and suggestions.

Replaces SQLite-based MetadataStore for portfolio operations.
All other metadata (instruments, jobs, runs) stays in SQLite.
"""


from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa


def _to_float(val):
    """Convert Decimal/numeric to float for JSON serialization."""
    if isinstance(val, Decimal):
        return float(val) if val else None
    return val


def _clean_row(d: dict) -> dict:
    """Clean a row dict — convert Decimals to floats."""
    return {k: _to_float(v) for k, v in d.items()}


class PgMetadataStore:
    """PostgreSQL-backed store for paper_signals + daily_suggestions."""

    def __init__(self, engine: sa.engine.Engine) -> None:
        self._engine = engine

    def close(self) -> None:
        pass  # engine manages connections

    # ── Paper Signals ──

    def open_papers(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT * FROM paper_signals WHERE status = 'OPEN'")).mappings().fetchall()
            return [_clean_row(dict(r)) for r in rows]

    def record_paper_signal(
        self,
        *,
        symbol: str,
        close_at_signal: float,
        qty: int,
        horizon_days: int,
        stop_pct: float,
        segment: str | None = None,
        side: str = "BUY",
        note: str | None = None,
        entry_date: str | None = None,
        position_value: float = 0.0,
        risk_amount: float = 0.0,
        horizon_label: str = "10d",
        capital_allocated: float = 0.0,
        conviction_score: float = 0.0,
        kelly_fraction: float = 0.0,
        hypothesis_id: int | None = None,
    ) -> int:
        values = {
            "created_at": datetime.now(UTC).isoformat(),
            "symbol": symbol,
            "segment": segment,
            "side": side,
            "close_at_signal": close_at_signal,
            "qty": qty,
            "horizon_days": horizon_days,
            "stop_pct": stop_pct,
            "status": "OPEN",
            "entry_date": entry_date,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "horizon_label": horizon_label,
            "capital_allocated": capital_allocated,
            "conviction_score": conviction_score,
            "kelly_fraction": kelly_fraction,
            "note": note,
            "hypothesis_id": hypothesis_id,
        }
        cols = ", ".join(values.keys())
        phs = ", ".join(f":{k}" for k in values)
        sql = sa.text(f"INSERT INTO paper_signals ({cols}) VALUES ({phs}) RETURNING id")
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            return result.scalar()

    def settle_paper_signal(
        self,
        paper_id: int,
        *,
        exit_date: str,
        exit_close: float,
        realized_net_bps: float,
        note: str | None = None,
        exit_reason: str = "HORIZON",
        days_held: int = 0,
        return_pct: float = 0.0,
        return_bps: float = 0.0,
        max_drawdown_bps: float = 0.0,
        peak_return_bps: float = 0.0,
    ) -> dict:
        values = {
            "id": paper_id,
            "exit_date": exit_date,
            "exit_close": exit_close,
            "realized_net_bps": realized_net_bps,
            "status": "SETTLED",
            "note": note,
            "exit_reason": exit_reason,
            "days_held": days_held,
            "return_pct": return_pct,
            "return_bps": return_bps,
            "max_drawdown_bps": max_drawdown_bps,
            "peak_return_bps": peak_return_bps,
        }
        sql = sa.text("""
            UPDATE paper_signals SET
                exit_date = :exit_date, exit_close = :exit_close,
                realized_net_bps = :realized_net_bps, status = :status,
                note = COALESCE(:note, note), exit_reason = :exit_reason,
                days_held = :days_held, return_pct = :return_pct,
                return_bps = :return_bps, max_drawdown_bps = :max_drawdown_bps,
                peak_return_bps = :peak_return_bps
            WHERE id = :id RETURNING *
        """)
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            row = result.mappings().fetchone()
            return _clean_row(dict(row)) if row else {}

    def papers_summary(self) -> dict:
        with self._engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open,
                    SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END) as settled,
                    SUM(CASE WHEN status = 'OPEN' THEN position_value ELSE 0 END) as total_position_value,
                    SUM(CASE WHEN status = 'OPEN' THEN risk_amount ELSE 0 END) as total_risk,
                    AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps,
                    SUM(CASE WHEN status = 'SETTLED' AND realized_net_bps > 0 THEN 1 ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END), 0) as hit_rate,
                    AVG(CASE WHEN status = 'SETTLED' THEN days_held END) as avg_days_held
                FROM paper_signals
            """)
                )
                .mappings()
                .fetchone()
            )
            return _clean_row(dict(r)) if r else {}

    def paper_trades_by_horizon(self) -> dict[str, dict]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.text("""
                SELECT
                    horizon_label,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END) as settled,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open,
                    AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps,
                    SUM(CASE WHEN status = 'SETTLED' AND realized_net_bps > 0 THEN 1 ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN status = 'SETTLED' THEN 1 ELSE 0 END), 0) as hit_rate,
                    AVG(CASE WHEN status = 'SETTLED' THEN days_held END) as avg_days_held
                FROM paper_signals GROUP BY horizon_label
            """)
                )
                .mappings()
                .fetchall()
            )
            return {r["horizon_label"]: _clean_row(dict(r)) for r in rows}

    def portfolio_summary(self) -> dict:
        with self._engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("""
                SELECT
                    SUM(CASE WHEN status = 'OPEN' THEN position_value ELSE 0 END) as total_position_value,
                    SUM(CASE WHEN status = 'OPEN' THEN risk_amount ELSE 0 END) as total_risk,
                    COUNT(CASE WHEN status = 'OPEN' THEN 1 END) as open_positions,
                    COUNT(CASE WHEN status = 'SETTLED' THEN 1 END) as total_trades,
                    AVG(CASE WHEN status = 'SETTLED' THEN realized_net_bps END) as avg_net_bps
                FROM paper_signals
            """)
                )
                .mappings()
                .fetchone()
            )
            return _clean_row(dict(r)) if r else {}

    def trade_log(self, *, horizon: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        conditions = []
        params = {}
        if horizon:
            conditions.append("horizon_label = :horizon")
            params["horizon"] = horizon
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params["limit"] = limit

        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.text(f"SELECT * FROM paper_signals {where} ORDER BY created_at DESC LIMIT :limit"), params
                )
                .mappings()
                .fetchall()
            )
            return [_clean_row(dict(r)) for r in rows]

    # ── Daily Suggestions ──

    def suggestions_by_date(self, date: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.text("SELECT * FROM daily_suggestions WHERE suggestion_date = :d ORDER BY symbol"), {"d": date}
                )
                .mappings()
                .fetchall()
            )
            return [_clean_row(dict(r)) for r in rows]

    def record_daily_suggestion(
        self,
        *,
        suggestion_date: str,
        symbol: str,
        segment: str | None = None,
        signal_type: str | None = None,
        direction: str = "BUY",
        close_at_signal: float = 0.0,
        deliv_pct: float | None = None,
        deliv_z: float | None = None,
        vol_z: float | None = None,
        entry_zone_low: float = 0.0,
        entry_zone_high: float = 0.0,
        stop_loss: float = 0.0,
        target_price: float = 0.0,
        horizon_days: int = 10,
        qty_suggested: int = 0,
        note: str | None = None,
        position_value: float = 0.0,
        risk_amount: float = 0.0,
        horizon_label: str = "10d",
        capital_allocated: float = 0.0,
        conviction_score: float = 0.0,
        kelly_fraction: float = 0.0,
    ) -> int:
        values = {
            "suggestion_date": suggestion_date,
            "symbol": symbol,
            "segment": segment,
            "signal_type": signal_type,
            "direction": direction,
            "close_at_signal": close_at_signal,
            "deliv_pct": deliv_pct,
            "deliv_z": deliv_z,
            "vol_z": vol_z,
            "entry_zone_low": entry_zone_low,
            "entry_zone_high": entry_zone_high,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "horizon_days": horizon_days,
            "qty_suggested": qty_suggested,
            "status": "PENDING",
            "note": note,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "horizon_label": horizon_label,
            "capital_allocated": capital_allocated,
            "conviction_score": conviction_score,
            "kelly_fraction": kelly_fraction,
        }
        cols = ", ".join(values.keys())
        phs = ", ".join(f":{k}" for k in values)
        sql = sa.text(f"INSERT INTO daily_suggestions ({cols}) VALUES ({phs}) RETURNING id")
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            return result.scalar()

    def pending_suggestions(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.text("SELECT * FROM daily_suggestions WHERE status = 'PENDING' ORDER BY suggestion_date, symbol")
                )
                .mappings()
                .fetchall()
            )
            return [_clean_row(dict(r)) for r in rows]

    def settle_daily_suggestion(
        self,
        suggestion_id: int,
        *,
        actual_exit_date: str,
        actual_exit_close: float,
        actual_return_bps: float,
        note: str | None = None,
    ) -> dict:
        values = {
            "id": suggestion_id,
            "actual_exit_date": actual_exit_date,
            "actual_exit_close": actual_exit_close,
            "actual_return_bps": actual_return_bps,
            "status": "REALIZED",
            "note": note,
        }
        sql = sa.text("""
            UPDATE daily_suggestions SET
                actual_exit_date = :actual_exit_date,
                actual_exit_close = :actual_exit_close,
                actual_return_bps = :actual_return_bps,
                status = :status,
                note = COALESCE(:note, note)
            WHERE id = :id RETURNING *
        """)
        with self._engine.begin() as conn:
            result = conn.execute(sql, values)
            row = result.mappings().fetchone()
            return _clean_row(dict(row)) if row else {}

    def suggestions_summary(self) -> dict:
        with self._engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'REALIZED' THEN 1 ELSE 0 END) as realized,
                    AVG(CASE WHEN status = 'REALIZED' THEN actual_return_bps END) as avg_net_bps,
                    SUM(CASE WHEN status = 'REALIZED' AND actual_return_bps > 0 THEN 1 ELSE 0 END) * 100.0 /
                        NULLIF(SUM(CASE WHEN status = 'REALIZED' THEN 1 ELSE 0 END), 0) as hit_rate
                FROM daily_suggestions
            """)
                )
                .mappings()
                .fetchone()
            )
            return _clean_row(dict(r)) if r else {}

    def suggestions_by_horizon(self) -> dict[str, dict]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.text("""
                SELECT
                    horizon_label,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'REALIZED' THEN 1 ELSE 0 END) as realized,
                    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                    AVG(CASE WHEN status = 'REALIZED' THEN actual_return_bps END) as avg_net_bps
                FROM daily_suggestions GROUP BY horizon_label
            """)
                )
                .mappings()
                .fetchall()
            )
            return {r["horizon_label"]: _clean_row(dict(r)) for r in rows}

    # ── Trade Journal ──

    def journal_record_on_entry(
        self,
        *,
        paper_trade_id: int,
        symbol: str,
        entry_date: str,
        entry_price: float,
        entry_signal: str,
        setup_type: str = "delivery_momentum",
        stop_loss: float = 0,
        target_price: float = 0,
        position_size: int = 0,
        risk_amount: float = 0,
        conviction: float = 0,
        sector: str = "",
        nifty_level: float = 0,
        market_breadth: float = 0,
        entry_rationale: str = "",
    ) -> int:
        """Auto-record journal entry when a trade is opened."""
        values = {
            "paper_trade_id": paper_trade_id,
            "symbol": symbol,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "entry_signal": entry_signal,
            "entry_rationale": entry_rationale or f"Signal: {entry_signal}",
            "setup_type": setup_type,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "position_size": position_size,
            "risk_amount": risk_amount,
            "conviction": conviction,
            "sector": sector,
            "nifty_level": nifty_level,
            "market_breadth": market_breadth,
        }
        cols = ", ".join(values.keys())
        phs = ", ".join(f":{k}" for k in values)
        sql = sa.text(f"INSERT INTO trade_journal ({cols}) VALUES ({phs}) RETURNING id")
        with self._engine.begin() as conn:
            return conn.execute(sql, values).scalar()

    def journal_record_on_exit(
        self,
        paper_trade_id: int,
        *,
        exit_date: str,
        exit_price: float,
        exit_reason: str = "",
        exit_rationale: str = "",
        days_held: int = 0,
        return_pct: float = 0,
        return_bps: float = 0,
        net_bps: float = 0,
    ) -> bool:
        """Update journal entry when a trade is closed."""
        with self._engine.begin() as conn:
            r = conn.execute(
                sa.text("""
                UPDATE trade_journal SET
                    exit_date = :exit_date, exit_price = :exit_price,
                    exit_reason = :exit_reason, exit_rationale = :exit_rationale,
                    days_held = :days_held, return_pct = :return_pct,
                    return_bps = :return_bps, net_bps = :net_bps
                WHERE paper_trade_id = :pid
            """),
                {
                    "pid": paper_trade_id,
                    "exit_date": exit_date,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "exit_rationale": exit_rationale,
                    "days_held": days_held,
                    "return_pct": return_pct,
                    "return_bps": return_bps,
                    "net_bps": net_bps,
                },
            )
            return r.rowcount > 0

    def journal_add_review(
        self,
        paper_trade_id: int,
        *,
        review_rating: int = 0,
        what_went_right: str = "",
        what_went_wrong: str = "",
        lessons_learned: str = "",
        would_repeat: bool = True,
        setup_quality: str = "",
        execution_grade: str = "",
        notes: str = "",
    ) -> bool:
        """Add post-trade review to journal."""
        from datetime import date as _date

        with self._engine.begin() as conn:
            r = conn.execute(
                sa.text("""
                UPDATE trade_journal SET
                    review_date = :rd, review_rating = :rr,
                    what_went_right = :wwr, what_went_wrong = :www,
                    lessons_learned = :ll, would_repeat = :wr,
                    setup_quality = :sq, execution_grade = :eg,
                    notes = :notes
                WHERE paper_trade_id = :pid
            """),
                {
                    "pid": paper_trade_id,
                    "rd": _date.today().isoformat(),
                    "rr": review_rating,
                    "wwr": what_went_right,
                    "www": what_went_wrong,
                    "ll": lessons_learned,
                    "wr": would_repeat,
                    "sq": setup_quality,
                    "eg": execution_grade,
                    "notes": notes,
                },
            )
            return r.rowcount > 0

    def journal_update_stop(
        self, paper_trade_id: int, *, date: str, old_stop: float, new_stop: float, reason: str = ""
    ) -> bool:
        """Record stop loss adjustment."""
        import json

        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT stop_history FROM trade_journal WHERE paper_trade_id = :pid"), {"pid": paper_trade_id}
            ).fetchone()
            if not row:
                return False
            history = json.loads(row[0] or "[]") if row[0] else []
            history.append({"date": date, "old": old_stop, "new": new_stop, "reason": reason})
            conn.execute(
                sa.text("""
                UPDATE trade_journal SET stop_moved = TRUE, stop_history = :sh
                WHERE paper_trade_id = :pid
            """),
                {"pid": paper_trade_id, "sh": json.dumps(history)},
            )
            conn.commit()
            return True

    def journal_entry(self, paper_trade_id: int) -> dict | None:
        """Get full journal entry for a trade."""
        with self._engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("SELECT * FROM trade_journal WHERE paper_trade_id = :pid"), {"pid": paper_trade_id}
                )
                .mappings()
                .fetchone()
            )
            return _clean_row(dict(r)) if r else None

    def journal_list(self, *, setup_type: str = "", reviewed: bool | None = None, limit: int = 50) -> list[dict]:
        """List journal entries with optional filters."""
        conditions = []
        params = {}
        if setup_type:
            conditions.append("setup_type = :st")
            params["st"] = setup_type
        if reviewed is True:
            conditions.append("review_date IS NOT NULL")
        elif reviewed is False:
            conditions.append("review_date IS NULL")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params["limit"] = limit

        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.text(f"SELECT * FROM trade_journal {where} ORDER BY entry_date DESC LIMIT :limit"), params
                )
                .mappings()
                .fetchall()
            )
            return [_clean_row(dict(r)) for r in rows]

    def journal_stats(self) -> dict:
        """Aggregate stats from journal: win/loss by setup, avg rating, review coverage."""
        with self._engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN net_bps > 0 THEN 1 ELSE 0 END) as winners,
                    SUM(CASE WHEN net_bps <= 0 THEN 1 ELSE 0 END) as losers,
                    AVG(net_bps) as avg_net_bps,
                    AVG(return_bps) as avg_return_bps,
                    AVG(review_rating) as avg_rating,
                    SUM(CASE WHEN review_date IS NOT NULL THEN 1 ELSE 0 END) as reviewed,
                    SUM(CASE WHEN would_repeat = TRUE THEN 1 ELSE 0 END) as would_repeat_count,
                    SUM(CASE WHEN would_repeat = FALSE THEN 1 ELSE 0 END) as would_not_repeat
                FROM trade_journal
            """)
                )
                .mappings()
                .fetchone()
            )
            base = _clean_row(dict(r)) if r else {}

            # By setup type
            rows = (
                conn.execute(
                    sa.text("""
                SELECT
                    setup_type,
                    COUNT(*) as n,
                    AVG(net_bps) as avg_net_bps,
                    AVG(review_rating) as avg_rating,
                    SUM(CASE WHEN net_bps > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
                FROM trade_journal
                GROUP BY setup_type ORDER BY n DESC
            """)
                )
                .mappings()
                .fetchall()
            )
            base["by_setup"] = [_clean_row(dict(r)) for r in rows]

            # Top lessons
            rows = (
                conn.execute(
                    sa.text("""
                SELECT lessons_learned, symbol, net_bps, setup_type
                FROM trade_journal
                WHERE lessons_learned IS NOT NULL AND lessons_learned != ''
                ORDER BY entry_date DESC LIMIT 10
            """)
                )
                .mappings()
                .fetchall()
            )
            base["recent_lessons"] = [_clean_row(dict(r)) for r in rows]

            return base
