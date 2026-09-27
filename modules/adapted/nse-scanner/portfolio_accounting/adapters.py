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


"""Read-only native position adapters and strategy-preserving signal mapping."""

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .snapshot import build_snapshot, number


def hull_snapshot(state: dict, as_of: str | None = None) -> dict:
    day = as_of or state.get("last_run")
    if not day:
        msg = "Hull state has no accounting date"
        raise ValueError(msg)
    positions, pending, legacy = [], [], []
    for raw in state.get("positions", []):
        status = raw.get("state")
        if status in {"WATCH", "READY", "PENDING"}:
            pending.append(raw)
            continue
        if status == "CANCELLED":
            continue
        if status not in {"OPEN", "TRAILING", "CLOSED", "CORPORATE_ACTION_REVIEW"} or not raw.get("quantity"):
            legacy.append(raw)
            continue
        row = dict(raw)
        row.update(
            status="REVIEW" if status == "CORPORATE_ACTION_REVIEW" else status,
            remaining_quantity=0 if status == "CLOSED" else raw["quantity"],
            # Older Hull state lacks per-position mark dates. Do not
            # present the state file's last run as proof every mark is fresh.
            mark_date=raw.get("mark_date"),
            entry_date=raw.get("entry_date"),
        )
        positions.append(row)
    return build_snapshot(
        "Hull",
        day,
        state["capital_base"],
        positions,
        pending,
        legacy=legacy,
        execution_model="LEGACY_HULL_RECORDED_FILLS",
    )


def v3_snapshot(rows: list, day: str, capital: float, entry_dates: dict | None = None) -> dict:
    positions, pending, legacy = [], [], []
    for original in rows:
        row = asdict(original) if is_dataclass(original) else dict(original)
        status = row.get("state")
        status = getattr(status, "value", status)
        if status in {"WATCH", "READY"}:
            row["reserved_capital"] = number(row["quantity"]) * number(row["entry"])
            pending.append(row)
            continue
        if status == "CANCELLED":
            continue
        if status not in {"OPEN", "PARTIAL", "TRAILING", "CLOSED"}:
            legacy.append(row)
            continue
        row.update(
            status=status, mark_date=row.get("updated_date"), entry_date=(entry_dates or {}).get(row["trade_id"])
        )
        positions.append(row)
    return build_snapshot(
        "V3", day, capital, positions, pending, legacy=legacy, execution_model="LEGACY_V3_RECORDED_FILLS"
    )


def read_v3(path: str | Path, day: str | None = None, capital: float | None = None) -> dict:
    """Never initialise or migrate the source database. Historical snapshots
    cannot be reconstructed from today's mutable positions; reject that request.
    """
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "v2_positions" not in tables:
            msg = "V3 positions table is unavailable"
            raise ValueError(msg)
        rows = [dict(r) for r in conn.execute("SELECT * FROM v2_positions ORDER BY trade_id")]
        newest = max((r["updated_date"] for r in rows), default=None)
        if day and newest and newest > day:
            msg = "V3 state contains later positions; use a dated database snapshot"
            raise ValueError(msg)
        stored = (
            conn.execute(
                "SELECT portfolio_date,capital_base FROM v2_portfolio_snapshots ORDER BY portfolio_date DESC LIMIT 1"
            ).fetchone()
            if "v2_portfolio_snapshots" in tables
            else None
        )
        if capital is None:
            if stored is None:
                msg = "V3 starting capital unavailable; specify the recorded capital"
                raise ValueError(msg)
            capital = stored["capital_base"]
        dates = {}
        if "v2_position_events" in tables:
            for r in conn.execute(
                "SELECT trade_id,MIN(event_date) day FROM v2_position_events WHERE to_state='OPEN' AND from_state IN ('WATCH','READY') GROUP BY trade_id"
            ):
                dates[r["trade_id"]] = r["day"]
    resolved_day = day or (stored["portfolio_date"] if stored else newest)
    if not resolved_day:
        msg = "V3 accounting date unavailable"
        raise ValueError(msg)
    return v3_snapshot(rows, resolved_day, capital, dates)


def penny_candidates(report: dict) -> list[dict]:
    return [
        {
            "symbol": r["symbol"],
            "score": r["score"],
            "entry": r["entry_low"],
            "entry_high": r["entry_high"],
            "stop": r["stop"],
            "target1": r["target1"],
            "target2": r["target2"],
            "max_stop_pct": 12.0,
        }
        for r in report.get("candidates", [])
        if r.get("state") == "READY"
    ]


def ladder_candidates(report: dict) -> list[dict]:
    # Candidate selection and levels remain those of the existing shadow engine.
    shadow = report.get("multi_horizon_shadow", report)
    if "candidates" not in shadow:
        msg = "Ladder report must include multi_horizon_shadow candidates"
        raise ValueError(msg)
    result = []
    for row in shadow.get("candidates", []):
        levels = row.get("trade_levels", {})
        if not levels.get("eligible_for_paper"):
            continue
        result.append(
            {
                "symbol": row["symbol"],
                "score": row.get("primary_score", 0),
                "entry": levels["entry_trigger"],
                "entry_high": levels["entry_trigger"] * 1.03,
                "stop": levels["stop"],
                "target1": levels["target_1"],
                "target2": levels["target_2"],
                "max_stop_pct": 8.0,
            }
        )
    return result


def legacy_records(path: str | Path | None) -> list[dict]:
    if path is None or not Path(path).exists():
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    positions = payload.get("positions", {})
    return list(positions.values()) if isinstance(positions, dict) else positions
