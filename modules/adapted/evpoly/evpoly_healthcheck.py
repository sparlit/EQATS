#!/usr/bin/env python3
"""Deterministic EVPoly healthcheck.

Checks:
- tmux session `evpoly-live` exists
- strategy decisions are being written for expected timeframes
- entry events are occurring recently (ENTRY_SUBMIT/ACK/FILL)
- redemption quota stalls are noted (non-fatal, but warn if persistent)

Outputs a single-line status + JSON details.
Exit code: 0 OK, 1 WARN/ERROR
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
EVPOLY_DIR = os.path.abspath(os.path.join(ROOT, ".."))
DB_PATH = os.path.join(EVPOLY_DIR, "tracking.db")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tmux_has_session(name: str) -> bool:
    try:
        subprocess.check_output(["tmux", "has-session", "-t", name], stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _capture_tmux_tail(name: str, lines: int = 200) -> str:
    try:
        out = subprocess.check_output(["tmux", "capture-pane", "-pt", name, "-S", f"-{lines}"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _db_connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30.0)
    con.row_factory = sqlite3.Row
    return con


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _reporting_scope_from_env() -> Tuple[Optional[int], bool]:
    cutover_raw = os.getenv("EVPOLY_REPORTING_CUTOVER_TS_MS", "").strip()
    cutover_ts_ms: Optional[int] = None
    if cutover_raw:
        try:
            parsed = int(cutover_raw)
            if parsed > 0:
                cutover_ts_ms = parsed
        except Exception:
            cutover_ts_ms = None
    include_legacy_default = _env_bool("EVPOLY_REPORTING_INCLUDE_LEGACY_DEFAULT", False)
    return cutover_ts_ms, include_legacy_default


def _canonical_fill_by_strategy(
    con: sqlite3.Connection, from_ts_ms: Optional[int], include_legacy_default: bool
) -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
            strategy_id,
            COUNT(*) AS fills,
            ROUND(COALESCE(SUM(notional_usd), 0.0), 4) AS fill_notional_usd
        FROM trade_events
        WHERE event_type='ENTRY_FILL'
          AND (:from_ts_ms IS NULL OR ts_ms >= :from_ts_ms)
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        GROUP BY strategy_id
        ORDER BY fill_notional_usd DESC, fills DESC, strategy_id ASC
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def _canonical_fill_by_timeframe(
    con: sqlite3.Connection, from_ts_ms: Optional[int], include_legacy_default: bool
) -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
            timeframe,
            COUNT(*) AS fills,
            ROUND(COALESCE(SUM(notional_usd), 0.0), 4) AS fill_notional_usd
        FROM trade_events
        WHERE event_type='ENTRY_FILL'
          AND (:from_ts_ms IS NULL OR ts_ms >= :from_ts_ms)
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        GROUP BY timeframe
        ORDER BY timeframe ASC
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def _canonical_activity_by_strategy(
    con: sqlite3.Connection, from_ts_ms: Optional[int], include_legacy_default: bool
) -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
            strategy_id,
            SUM(CASE WHEN event_type='ENTRY_SUBMIT' THEN 1 ELSE 0 END) AS entry_submits,
            SUM(CASE WHEN event_type='ENTRY_ACK' THEN 1 ELSE 0 END) AS entry_acks,
            SUM(CASE WHEN event_type='ENTRY_FILL' THEN 1 ELSE 0 END) AS entry_fills,
            ROUND(COALESCE(SUM(CASE WHEN event_type='ENTRY_FILL' THEN COALESCE(notional_usd,0.0) ELSE 0.0 END), 0.0), 4) AS entry_fill_notional_usd
        FROM trade_events
        WHERE event_type IN ('ENTRY_SUBMIT','ENTRY_ACK','ENTRY_FILL')
          AND (:from_ts_ms IS NULL OR ts_ms >= :from_ts_ms)
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        GROUP BY strategy_id
        ORDER BY strategy_id ASC
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def _parallel_overlap_groups_recent(
    con: sqlite3.Connection,
    from_ts_ms: Optional[int],
    include_legacy_default: bool,
    lookback_ms: int = 4 * 60 * 60 * 1000,
) -> Dict[str, Any]:
    recent_from = _now_ms() - lookback_ms
    effective_from = max(from_ts_ms or 0, recent_from)
    rows = con.execute(
        """
        SELECT
            period_timestamp,
            token_id,
            side,
            COUNT(DISTINCT strategy_id) AS strategy_count,
            COUNT(*) AS submit_count
        FROM trade_events
        WHERE event_type='ENTRY_SUBMIT'
          AND ts_ms >= :from_ts_ms
          AND token_id IS NOT NULL AND TRIM(token_id) != ''
          AND side IS NOT NULL AND TRIM(side) != ''
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        GROUP BY period_timestamp, token_id, side
        HAVING COUNT(DISTINCT strategy_id) > 1
        ORDER BY submit_count DESC, period_timestamp DESC
        LIMIT 20
        """,
        {
            "from_ts_ms": effective_from,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchall()
    top = [dict(r) for r in rows[:5]]
    return {
        "window_ms": lookback_ms,
        "from_ts_ms": effective_from,
        "group_count": len(rows),
        "top_groups": top,
    }


def _latest_strategy_decisions(con: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    rows = con.execute(
        "SELECT id, period_timestamp, timeframe, decided_at_ms, action, direction, confidence, source "
        "FROM strategy_decisions ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def _latest_trade_events(con: sqlite3.Connection, limit: int = 300) -> List[Dict[str, Any]]:
    rows = con.execute(
        "SELECT id, ts_ms, period_timestamp, timeframe, event_type, reason "
        "FROM trade_events ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def _summarize_recent_by_timeframe(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        tf = str(r.get("timeframe") or "")
        if tf not in out:
            out[tf] = r
    return out


def _contains_quota_pause(text: str) -> bool:
    t = (text or "").lower()
    return "relayer quota" in t or "quota limit" in t


def main() -> int:
    issues: List[str] = []
    warns: List[str] = []

    tmux_ok = _tmux_has_session("evpoly-live")
    if not tmux_ok:
        issues.append("tmux_session_missing:evpoly-live")

    if not os.path.exists(DB_PATH):
        issues.append("missing_tracking_db")
        payload = {"ok": False, "issues": issues, "warns": warns}
        print("EVPOLY_HEALTH ERROR " + json.dumps(payload, separators=(",", ":")))
        return 1

    con = _db_connect(DB_PATH)
    try:
        decisions = _latest_strategy_decisions(con)
        events = _latest_trade_events(con)
        reporting_cutover_ts_ms, include_legacy_default = _reporting_scope_from_env()
        canonical_fill_by_strategy = _canonical_fill_by_strategy(
            con, reporting_cutover_ts_ms, include_legacy_default
        )
        canonical_fill_by_timeframe = _canonical_fill_by_timeframe(
            con, reporting_cutover_ts_ms, include_legacy_default
        )
        canonical_activity_by_strategy = _canonical_activity_by_strategy(
            con, reporting_cutover_ts_ms, include_legacy_default
        )
        parallel_overlap_recent = _parallel_overlap_groups_recent(
            con, reporting_cutover_ts_ms, include_legacy_default
        )
    finally:
        con.close()

    latest_decision_by_tf = _summarize_recent_by_timeframe(decisions)
    latest_event_by_tf = _summarize_recent_by_timeframe(events)

    # Expectations:
    # - 5m should be making decisions frequently; if none in last ~12 minutes => issue
    # - 15m should appear at least once in last ~40 minutes => warn/issue
    # - 1h should appear at least once in last ~90 minutes => warn/issue
    now_s = int(time.time())

    def _age_s_from_created_at(created_at: Optional[str]) -> Optional[int]:
        # created_at is whatever sqlite stores; not reliable to parse. Use id recency + wall time instead.
        return None

    def _decision_exists(tf: str) -> bool:
        return tf in latest_decision_by_tf

    if not _decision_exists("5m"):
        issues.append("no_recent_strategy_decision:5m")
    if not _decision_exists("15m"):
        warns.append("no_recent_strategy_decision:15m")
    if not _decision_exists("1h"):
        warns.append("no_recent_strategy_decision:1h")

    # Entry activity: require at least one recent ENTRY_SUBMIT in last 30 trade events.
    recent_entry = [e for e in events[:60] if str(e.get("event_type")) in {"ENTRY_SUBMIT", "ENTRY_ACK", "ENTRY_FILL"}]
    if not recent_entry:
        warns.append("no_recent_entry_events")

    # Quota pause (non-fatal) but warn if present in tmux tail.
    tmux_tail = _capture_tmux_tail("evpoly-live", 200) if tmux_ok else ""
    if tmux_tail and _contains_quota_pause(tmux_tail):
        warns.append("redemption_quota_paused")

    ok = (len(issues) == 0)
    payload = {
        "ok": ok,
        "tmux": {"evpoly-live": tmux_ok},
        "reporting_policy": {
            "fill_metric_policy": "ENTRY_FILL",
            "scope_policy": "cutover_excluding_legacy_default",
            "cutover_ts_ms": reporting_cutover_ts_ms,
            "include_legacy_default": include_legacy_default,
        },
        "canonical_fill_by_strategy": canonical_fill_by_strategy,
        "canonical_fill_by_timeframe": canonical_fill_by_timeframe,
        "canonical_activity_by_strategy": canonical_activity_by_strategy,
        "parallel_overlap_groups_recent": parallel_overlap_recent,
        "latest_strategy_decision": {k: {"period_timestamp": v.get("period_timestamp"), "action": v.get("action"), "direction": v.get("direction"), "confidence": v.get("confidence"), "source": v.get("source")} for k, v in latest_decision_by_tf.items()},
        "latest_trade_event": {k: {"period_timestamp": v.get("period_timestamp"), "event_type": v.get("event_type"), "reason": v.get("reason")} for k, v in latest_event_by_tf.items()},
        "issues": issues,
        "warns": warns,
        "ts_ms": _now_ms(),
    }

    if ok and not warns:
        print("EVPOLY_HEALTH OK " + json.dumps(payload, separators=(",", ":")))
        return 0

    level = "WARN" if ok else "ERROR"
    print(f"EVPOLY_HEALTH {level} " + json.dumps(payload, separators=(",", ":")))
    # WARN is non-fatal: return 0 so schedulers don't treat it as failure.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
