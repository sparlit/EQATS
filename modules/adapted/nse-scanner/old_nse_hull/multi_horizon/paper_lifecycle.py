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


"""Persistent next-session simulated lifecycle; no broker interaction exists here."""

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

MAX_OPEN_POSITIONS = 10
MAX_TOTAL_OPEN_RISK_PCT = 20.0


def _load(path: Path) -> dict:
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"schema_version": 1, "watchlist": {}, "positions": {}, "events": []}
    )


def update(path: str | Path, as_of_date: str, candidates: list[dict], market_rows: list[dict] | None = None) -> dict:
    """Advance simulated positions using completed EOD bars and write state idempotently."""
    target = Path(path)
    state = _load(target)
    watchlist, positions = state.setdefault("watchlist", {}), state.setdefault("positions", {})
    events: list[dict] = []
    candidate_map = {str(row["symbol"]): row for row in (market_rows or candidates)}
    for symbol, pending in list(watchlist.items()):
        row = candidate_map.get(symbol)
        if row is None or as_of_date <= pending["created_date"]:
            continue
        if float(row["high"]) >= pending["entry_trigger"]:
            position = {**pending, "entered_date": as_of_date, "status": "OPEN", "target_1_hit": False}
            positions[symbol] = position
            del watchlist[symbol]
            events.append(
                {"date": as_of_date, "symbol": symbol, "event": "PAPER_ENTERED", "price": pending["entry_trigger"]}
            )
    for symbol, position in list(positions.items()):
        row = candidate_map.get(symbol)
        if position.get("status") != "OPEN" or row is None or as_of_date <= position["entered_date"]:
            continue
        if float(row["low"]) <= position["stop"]:
            position["status"] = "STOPPED"
            position["exited_date"] = as_of_date
            position["exit_price"] = position["stop"]
            events.append({"date": as_of_date, "symbol": symbol, "event": "PAPER_STOPPED", "price": position["stop"]})
            continue
        if not position["target_1_hit"] and float(row["high"]) >= position["target_1"]:
            position["target_1_hit"] = True
            events.append(
                {"date": as_of_date, "symbol": symbol, "event": "PAPER_T1_HIT", "price": position["target_1"]}
            )
        if float(row["high"]) >= position["target_2"]:
            position["status"] = "TARGET_2_HIT"
            position["exited_date"] = as_of_date
            position["exit_price"] = position["target_2"]
            events.append(
                {"date": as_of_date, "symbol": symbol, "event": "PAPER_TARGET_2_HIT", "price": position["target_2"]}
            )
    open_risk = sum(float(item.get("risk_pct", 0)) for item in positions.values() if item.get("status") == "OPEN")
    for symbol, row in candidate_map.items():
        levels = row.get("trade_levels", {})
        capacity = (
            sum(item.get("status") == "OPEN" for item in positions.values()) + len(watchlist) < MAX_OPEN_POSITIONS
        )
        risk_ok = open_risk + float(levels.get("risk_pct", 0)) <= MAX_TOTAL_OPEN_RISK_PCT
        if (
            symbol not in watchlist
            and symbol not in positions
            and levels.get("eligible_for_paper")
            and capacity
            and risk_ok
        ):
            watchlist[symbol] = {"symbol": symbol, "created_date": as_of_date, **levels}
            open_risk += float(levels.get("risk_pct", 0))
            events.append(
                {"date": as_of_date, "symbol": symbol, "event": "PAPER_WATCHING", "price": levels["entry_trigger"]}
            )
    state["events"] = (state.get("events", []) + events)[-500:]
    state["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "watching": len(watchlist),
        "open": sum(item["status"] == "OPEN" for item in positions.values()),
        "closed": sum(item["status"] != "OPEN" for item in positions.values()),
        "open_risk_pct": round(open_risk, 2),
        "limits": {"max_open_positions": MAX_OPEN_POSITIONS, "max_total_open_risk_pct": MAX_TOTAL_OPEN_RISK_PCT},
        "events_today": events,
    }
