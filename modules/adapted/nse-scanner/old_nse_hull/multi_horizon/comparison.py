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


"""Git-backed, idempotent shadow-versus-baseline comparison ledger."""

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

TARGET_SESSIONS = 20


def summarize(path: str | Path) -> dict:
    """Read the committed ledger without mutating it."""
    target = Path(path)
    if not target.exists():
        return {
            "target_sessions": TARGET_SESSIONS,
            "sessions_observed": 0,
            "sessions_remaining": TARGET_SESSIONS,
            "validation_ready": False,
            "average_baseline_candidates": 0,
            "average_shadow_candidates": 0,
            "average_overlap": 0,
            "recent_sessions": [],
        }
    payload = json.loads(target.read_text(encoding="utf-8"))
    sessions = dict(sorted(payload.get("sessions", {}).items()))
    rows = list(sessions.values())
    count = len(rows)
    return {
        "target_sessions": TARGET_SESSIONS,
        "sessions_observed": count,
        "sessions_remaining": max(0, TARGET_SESSIONS - count),
        "validation_ready": count >= TARGET_SESSIONS,
        "average_baseline_candidates": round(sum(len(row["baseline_symbols"]) for row in rows) / count, 2)
        if count
        else 0,
        "average_shadow_candidates": round(sum(len(row["shadow_symbols"]) for row in rows) / count, 2) if count else 0,
        "average_overlap": round(sum(len(row["overlap_symbols"]) for row in rows) / count, 2) if count else 0,
        "recent_sessions": [{"as_of_date": day, **data} for day, data in list(sessions.items())[-5:]],
    }


def update_summary(path: str | Path, as_of_date: str, baseline_symbols: list[str], shadow_rows: list[dict]) -> dict:
    """Persist one session and calculate the validation status.

    The file is committed by the existing scheduled workflow. This avoids
    treating a disposable GitHub Actions SQLite database as lifecycle truth.
    """
    target = Path(path)
    previous = (
        json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"schema_version": 1, "sessions": {}}
    )
    sessions = previous.setdefault("sessions", {})
    shadow_symbols = sorted(str(row["symbol"]) for row in shadow_rows)
    baseline = sorted(set(map(str, baseline_symbols)))
    sessions[as_of_date] = {
        "baseline_symbols": baseline,
        "shadow_symbols": shadow_symbols,
        "overlap_symbols": sorted(set(baseline) & set(shadow_symbols)),
        "newly_qualified": sum(row.get("lifecycle_status") == "NEWLY_QUALIFIED" for row in shadow_rows),
        "upgraded": sum(row.get("lifecycle_status") == "UPGRADED" for row in shadow_rows),
    }
    ordered = dict(sorted(sessions.items())[-TARGET_SESSIONS:])
    previous["sessions"] = ordered
    previous["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    target.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = summarize(target)
    summary["latest"] = ordered.get(as_of_date, {})
    return summary
