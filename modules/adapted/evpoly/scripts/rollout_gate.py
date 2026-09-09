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


#!/usr/bin/env python3
"""EVPoly runtime rollout gate checker.

This script evaluates deterministic numeric gates from tracking.db and returns:
- EVPOLY_ROLLOUT_GATE PASS <json>
- EVPOLY_ROLLOUT_GATE FAIL <json>

Exit code:
- 0 => PASS
- 1 => FAIL
"""


import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
EVPOLY_DIR = os.path.abspath(os.path.join(ROOT, ".."))
DEFAULT_DB = os.path.join(EVPOLY_DIR, "tracking.db")


def now_ms() -> int:
    return int(time.time() * 1000)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except Exception:
        return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default


def db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return int(row["n"] or 0) > 0


def table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not table_exists(conn, table_name):
        return False
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"] or "").strip().lower() == column_name.strip().lower() for row in rows)


@dataclass
class GateResult:
    name: str
    passed: bool
    metric: dict[str, Any]
    threshold: dict[str, Any]
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "metric": self.metric,
            "threshold": self.threshold,
            "reason": self.reason,
        }


def _strategy_base_rows(
    conn: sqlite3.Connection, from_ts_ms: int, include_legacy_default: bool
) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            strategy_id,
            SUM(CASE WHEN event_type='ENTRY_SUBMIT' THEN 1 ELSE 0 END) AS entry_submits,
            SUM(CASE WHEN event_type='ENTRY_FAILED' THEN 1 ELSE 0 END) AS entry_failed
        FROM trade_events
        WHERE ts_ms >= :from_ts_ms
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        GROUP BY strategy_id
        ORDER BY strategy_id ASC
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        strategy_id = str(row["strategy_id"] or "").strip()
        if not strategy_id:
            continue
        submits = int(row["entry_submits"] or 0)
        failed = int(row["entry_failed"] or 0)
        ratio = ((failed / submits) * 100.0) if submits > 0 else 0.0
        out[strategy_id] = {
            "strategy_id": strategy_id,
            "entry_submits": submits,
            "entry_failed": failed,
            "entry_failed_ratio_pct": ratio,
        }
    return out


def _submit_storm_groups(conn: sqlite3.Connection, strategy_id: str, from_ts_ms: int, fresh_from_ts_ms: int) -> int:
    value = conn.execute(
        """
        SELECT COALESCE(COUNT(*), 0) FROM (
          SELECT period_timestamp, token_id, side
          FROM trade_events
          WHERE ts_ms >= :from_ts_ms
            AND strategy_id = :strategy_id
            AND event_type = 'ENTRY_SUBMIT'
            AND token_id IS NOT NULL
            AND TRIM(token_id) != ''
            AND side IS NOT NULL
            AND TRIM(side) != ''
          GROUP BY period_timestamp, token_id, side
          HAVING COUNT(*) > 5
             AND MAX(ts_ms) >= :fresh_from_ts_ms
        )
        """,
        {
            "from_ts_ms": from_ts_ms,
            "fresh_from_ts_ms": fresh_from_ts_ms,
            "strategy_id": strategy_id,
        },
    ).fetchone()
    return int(value[0] or 0)


def _integrity_summary(conn: sqlite3.Connection, from_ts_ms: int) -> tuple[int, int]:
    if not table_exists(conn, "strategy_feature_snapshots_v1"):
        return 0, 0
    has_rejections = table_exists(conn, "strategy_feature_snapshot_transition_rejections")
    duplicate_snapshot_rows = conn.execute(
        """
        SELECT COALESCE(COUNT(*), 0) FROM (
          SELECT snapshot_id
          FROM strategy_feature_snapshots_v1
          WHERE intent_ts_ms >= :from_ts_ms
          GROUP BY snapshot_id
          HAVING COUNT(*) > 1
        )
        """,
        {"from_ts_ms": from_ts_ms},
    ).fetchone()
    if has_rejections:
        invalid_transitions = conn.execute(
            """
            SELECT COUNT(*)
            FROM strategy_feature_snapshot_transition_rejections
            WHERE rejected_at_ms >= :from_ts_ms
            """,
            {"from_ts_ms": from_ts_ms},
        ).fetchone()
        invalid_count = int(invalid_transitions[0] or 0)
    else:
        invalid_count = 0
    return int(duplicate_snapshot_rows[0] or 0), invalid_count


def _fill_parity(conn: sqlite3.Connection, from_ts_ms: int, include_legacy_default: bool) -> dict[str, Any]:
    if not table_exists(conn, "pending_orders"):
        return {
            "filled_orders": 0,
            "filled_usd": 0.0,
            "fill_events": 0,
            "fill_events_usd": 0.0,
            "count_gap": 0,
            "usd_gap": 0.0,
            "count_gap_ratio": 0.0,
            "usd_gap_ratio": 0.0,
        }
    pending_fill_ts_col = (
        "filled_at_ms" if table_has_column(conn, "pending_orders", "filled_at_ms") else "updated_at_ms"
    )
    fill_source_table = "fills_v2" if table_exists(conn, "fills_v2") else "trade_events"
    if fill_source_table == "fills_v2":
        fill_where = """
        FROM fills_v2
        WHERE side='BUY'
          AND ts_ms >= :from_ts_ms
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        """
    else:
        fill_where = """
        FROM trade_events
        WHERE event_type='ENTRY_FILL'
          AND ts_ms >= :from_ts_ms
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        """
    pending = conn.execute(
        f"""
        SELECT
            COUNT(*) AS filled_orders,
            COALESCE(SUM(size_usd), 0.0) AS filled_usd
        FROM pending_orders
        WHERE side='BUY'
          AND status='FILLED'
          AND COALESCE({pending_fill_ts_col}, updated_at_ms) >= :from_ts_ms
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchone()
    events = conn.execute(
        f"""
        SELECT
            COUNT(*) AS fill_events,
            COALESCE(SUM(notional_usd), 0.0) AS fill_events_usd
        {fill_where}
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchone()
    filled_orders = int(pending["filled_orders"] or 0)
    filled_usd = float(pending["filled_usd"] or 0.0)
    fill_events = int(events["fill_events"] or 0)
    fill_events_usd = float(events["fill_events_usd"] or 0.0)

    count_gap = abs(filled_orders - fill_events)
    usd_gap = abs(filled_usd - fill_events_usd)
    denom_orders = max(filled_orders, 1)
    denom_usd = max(abs(filled_usd), 1.0)
    count_gap_ratio = count_gap / denom_orders
    usd_gap_ratio = usd_gap / denom_usd
    return {
        "filled_orders": filled_orders,
        "filled_usd": filled_usd,
        "fill_events": fill_events,
        "fill_events_usd": fill_events_usd,
        "count_gap": count_gap,
        "usd_gap": usd_gap,
        "count_gap_ratio": count_gap_ratio,
        "usd_gap_ratio": usd_gap_ratio,
    }


def _settlement_drift(conn: sqlite3.Connection, from_ts_ms: int, include_legacy_default: bool) -> dict[str, Any]:
    if not table_exists(conn, "settlements_v2"):
        return {
            "settled_rows": 0,
            "settled_pnl_usd": 0.0,
            "market_close_exit_rows": 0,
            "market_close_exit_pnl_usd": 0.0,
            "pnl_gap_usd": 0.0,
            "pnl_gap_ratio": 0.0,
        }
    if table_has_column(conn, "settlements_v2", "settled_at_ms"):
        settled_ts_col = "settled_at_ms"
    elif table_has_column(conn, "settlements_v2", "ts_ms"):
        settled_ts_col = "ts_ms"
    else:
        settled_ts_col = "created_at_ms"
    settled = conn.execute(
        f"""
        SELECT
            COUNT(*) AS settled_rows,
            COALESCE(SUM(settled_pnl_usd), 0.0) AS settled_pnl_usd
        FROM settlements_v2
        WHERE {settled_ts_col} >= :from_ts_ms
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchone()
    exits = conn.execute(
        """
        SELECT
            COUNT(*) AS market_close_exit_rows,
            COALESCE(SUM(pnl_usd), 0.0) AS market_close_exit_pnl_usd
        FROM trade_events
        WHERE event_type='EXIT'
          AND ts_ms >= :from_ts_ms
          AND COALESCE(LOWER(reason), '') LIKE '%market_close%'
          AND (:include_legacy = 1 OR strategy_id != 'legacy_default')
        """,
        {
            "from_ts_ms": from_ts_ms,
            "include_legacy": 1 if include_legacy_default else 0,
        },
    ).fetchone()

    settled_rows = int(settled["settled_rows"] or 0)
    settled_pnl = float(settled["settled_pnl_usd"] or 0.0)
    exit_rows = int(exits["market_close_exit_rows"] or 0)
    exit_pnl = float(exits["market_close_exit_pnl_usd"] or 0.0)
    gap_usd = abs(settled_pnl - exit_pnl)
    ratio = gap_usd / max(abs(settled_pnl), 1.0)
    return {
        "settled_rows": settled_rows,
        "settled_pnl_usd": settled_pnl,
        "market_close_exit_rows": exit_rows,
        "market_close_exit_pnl_usd": exit_pnl,
        "pnl_gap_usd": gap_usd,
        "pnl_gap_ratio": ratio,
    }


def _snapshot_coverage(conn: sqlite3.Connection, from_ts_ms: int, strategy_id: str) -> dict[str, Any]:
    if not table_exists(conn, "strategy_feature_snapshots_v1"):
        return {
            "strategy_id": strategy_id,
            "entry_submits": 0,
            "snapshot_submit_rows": 0,
            "coverage_ratio": 0.0,
        }
    submits = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN event_type='ENTRY_SUBMIT' THEN 1 ELSE 0 END), 0)
        FROM trade_events
        WHERE strategy_id=:strategy_id
          AND ts_ms >= :from_ts_ms
        """,
        {"strategy_id": strategy_id, "from_ts_ms": from_ts_ms},
    ).fetchone()
    snapshots = conn.execute(
        """
        SELECT COUNT(*)
        FROM strategy_feature_snapshots_v1
        WHERE strategy_id=:strategy_id
          AND submit_ts_ms IS NOT NULL
          AND submit_ts_ms >= :from_ts_ms
          AND intent_status='submitted'
        """,
        {"strategy_id": strategy_id, "from_ts_ms": from_ts_ms},
    ).fetchone()
    submit_count = int(submits[0] or 0)
    snapshot_submit_rows = int(snapshots[0] or 0)
    coverage_ratio = (snapshot_submit_rows / submit_count) if submit_count > 0 else 1.0
    return {
        "strategy_id": strategy_id,
        "entry_submits": submit_count,
        "snapshot_submit_rows": snapshot_submit_rows,
        "coverage_ratio": coverage_ratio,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EVPoly rollout gate checker")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to tracking.db")
    parser.add_argument(
        "--strategy-hours",
        type=int,
        default=env_int("EVPOLY_GATE_STRATEGY_HOURS", 4),
        help="Lookback window (hours) for strategy/churn/fill checks",
    )
    parser.add_argument(
        "--integrity-hours",
        type=int,
        default=env_int("EVPOLY_GATE_INTEGRITY_HOURS", 24),
        help="Lookback window (hours) for integrity + settlement drift checks",
    )
    parser.add_argument(
        "--include-legacy-default",
        action="store_true",
        default=env_bool("EVPOLY_REPORTING_INCLUDE_LEGACY_DEFAULT", False),
        help="Include legacy_default rows in checks",
    )
    parser.add_argument(
        "--max-entry-failed-ratio-pct",
        type=float,
        default=env_float("EVPOLY_GATE_MAX_ENTRY_FAILED_RATIO_PCT", 35.0),
    )
    parser.add_argument(
        "--max-submit-storm-groups",
        type=int,
        default=env_int("EVPOLY_GATE_MAX_SUBMIT_STORM_GROUPS", 0),
    )
    parser.add_argument(
        "--storm-fresh-minutes",
        type=int,
        default=env_int("EVPOLY_GATE_STORM_FRESH_MINUTES", 30),
        help="Only count storm groups with most-recent submit inside this trailing window",
    )
    parser.add_argument(
        "--max-duplicate-snapshot-rows",
        type=int,
        default=env_int("EVPOLY_GATE_MAX_DUPLICATE_SNAPSHOT_ROWS", 0),
    )
    parser.add_argument(
        "--max-invalid-transition-rejections",
        type=int,
        default=env_int("EVPOLY_GATE_MAX_INVALID_TRANSITION_REJECTIONS", 0),
    )
    parser.add_argument(
        "--max-fill-gap-ratio",
        type=float,
        default=env_float("EVPOLY_GATE_MAX_FILL_GAP_RATIO", 0.35),
    )
    parser.add_argument(
        "--max-fill-gap-usd",
        type=float,
        default=env_float("EVPOLY_GATE_MAX_FILL_GAP_USD", 100.0),
    )
    parser.add_argument(
        "--min-snapshot-coverage-ratio",
        type=float,
        default=env_float("EVPOLY_GATE_MIN_SNAPSHOT_COVERAGE_RATIO", 0.80),
    )
    parser.add_argument(
        "--min-submits-for-coverage-check",
        type=int,
        default=env_int("EVPOLY_GATE_MIN_SUBMITS_FOR_COVERAGE_CHECK", 3),
    )
    parser.add_argument(
        "--max-settlement-drift-ratio",
        type=float,
        default=env_float("EVPOLY_GATE_MAX_SETTLEMENT_DRIFT_RATIO", 0.30),
    )
    parser.add_argument(
        "--max-settlement-drift-usd",
        type=float,
        default=env_float("EVPOLY_GATE_MAX_SETTLEMENT_DRIFT_USD", 100.0),
    )
    parser.add_argument(
        "--json-pretty",
        action="store_true",
        help="Print indented JSON payload",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not os.path.exists(args.db):
        payload = {"ok": False, "error": f"db_not_found:{args.db}"}
        print("EVPOLY_ROLLOUT_GATE FAIL " + json.dumps(payload, separators=(",", ":")))
        return 1

    now = now_ms()
    strategy_from_ts_ms = now - max(args.strategy_hours, 1) * 3_600_000
    integrity_from_ts_ms = now - max(args.integrity_hours, 1) * 3_600_000
    include_legacy = bool(args.include_legacy_default)

    conn = db_connect(args.db)
    checks: list[GateResult] = []
    strategy_rows: dict[str, dict[str, Any]] = {}
    try:
        has_snapshots = table_exists(conn, "strategy_feature_snapshots_v1")
        has_rejections = table_exists(conn, "strategy_feature_snapshot_transition_rejections")
        has_pending_orders = table_exists(conn, "pending_orders")
        has_settlements = table_exists(conn, "settlements_v2")

        checks.append(
            GateResult(
                name="schema.strategy_feature_snapshots_v1_exists",
                passed=has_snapshots,
                metric={"exists": has_snapshots},
                threshold={"required": True},
                reason=("required snapshot table present" if has_snapshots else "required snapshot table missing"),
            )
        )
        checks.append(
            GateResult(
                name="schema.strategy_feature_snapshot_transition_rejections_exists",
                passed=has_rejections,
                metric={"exists": has_rejections},
                threshold={"required": True},
                reason=(
                    "required transition-rejections table present"
                    if has_rejections
                    else "required transition-rejections table missing"
                ),
            )
        )
        checks.append(
            GateResult(
                name="schema.pending_orders_exists",
                passed=has_pending_orders,
                metric={"exists": has_pending_orders},
                threshold={"required": True},
                reason=(
                    "required pending_orders table present"
                    if has_pending_orders
                    else "required pending_orders table missing"
                ),
            )
        )
        checks.append(
            GateResult(
                name="schema.settlements_v2_exists",
                passed=has_settlements,
                metric={"exists": has_settlements},
                threshold={"required": True},
                reason=(
                    "required settlements_v2 table present"
                    if has_settlements
                    else "required settlements_v2 table missing"
                ),
            )
        )

        strategy_rows = _strategy_base_rows(conn, strategy_from_ts_ms, include_legacy)
        storm_fresh_from_ts_ms = max(
            strategy_from_ts_ms,
            now - max(args.storm_fresh_minutes, 1) * 60_000,
        )

        for strategy_id, row in sorted(strategy_rows.items()):
            storm_groups = _submit_storm_groups(conn, strategy_id, strategy_from_ts_ms, storm_fresh_from_ts_ms)
            failed_ratio = float(row["entry_failed_ratio_pct"])
            checks.append(
                GateResult(
                    name=f"{strategy_id}.entry_failed_ratio",
                    passed=failed_ratio <= args.max_entry_failed_ratio_pct,
                    metric={
                        "entry_submits": row["entry_submits"],
                        "entry_failed": row["entry_failed"],
                        "entry_failed_ratio_pct": round(failed_ratio, 4),
                    },
                    threshold={"max_entry_failed_ratio_pct": args.max_entry_failed_ratio_pct},
                    reason=(
                        "entry_failed ratio within threshold"
                        if failed_ratio <= args.max_entry_failed_ratio_pct
                        else "entry_failed ratio above threshold"
                    ),
                )
            )
            checks.append(
                GateResult(
                    name=f"{strategy_id}.submit_storm_groups",
                    passed=storm_groups <= args.max_submit_storm_groups,
                    metric={"submit_storm_groups": storm_groups},
                    threshold={"max_submit_storm_groups": args.max_submit_storm_groups},
                    reason=(
                        "submit storm groups within threshold"
                        if storm_groups <= args.max_submit_storm_groups
                        else "submit storm groups above threshold"
                    ),
                )
            )

            coverage = _snapshot_coverage(conn, strategy_from_ts_ms, strategy_id)
            submit_count = int(coverage["entry_submits"])
            if submit_count >= args.min_submits_for_coverage_check:
                cov_ratio = float(coverage["coverage_ratio"])
                checks.append(
                    GateResult(
                        name=f"{strategy_id}.snapshot_coverage",
                        passed=cov_ratio >= args.min_snapshot_coverage_ratio,
                        metric=coverage,
                        threshold={
                            "min_snapshot_coverage_ratio": args.min_snapshot_coverage_ratio,
                            "min_submits_for_coverage_check": args.min_submits_for_coverage_check,
                        },
                        reason=(
                            "snapshot coverage above threshold"
                            if cov_ratio >= args.min_snapshot_coverage_ratio
                            else "snapshot coverage below threshold"
                        ),
                    )
                )

        dup_rows, invalid_transitions = _integrity_summary(conn, integrity_from_ts_ms)
        checks.append(
            GateResult(
                name="integrity.duplicate_snapshot_rows",
                passed=dup_rows <= args.max_duplicate_snapshot_rows,
                metric={"duplicate_snapshot_rows": dup_rows},
                threshold={"max_duplicate_snapshot_rows": args.max_duplicate_snapshot_rows},
                reason=(
                    "duplicate snapshot rows within threshold"
                    if dup_rows <= args.max_duplicate_snapshot_rows
                    else "duplicate snapshot rows above threshold"
                ),
            )
        )
        checks.append(
            GateResult(
                name="integrity.invalid_transition_rejections",
                passed=invalid_transitions <= args.max_invalid_transition_rejections,
                metric={"invalid_transition_rejections": invalid_transitions},
                threshold={"max_invalid_transition_rejections": args.max_invalid_transition_rejections},
                reason=(
                    "invalid transition rejections within threshold"
                    if invalid_transitions <= args.max_invalid_transition_rejections
                    else "invalid transition rejections above threshold"
                ),
            )
        )

        fill_parity = _fill_parity(conn, strategy_from_ts_ms, include_legacy)
        fill_ok = (
            (fill_parity["count_gap_ratio"] <= args.max_fill_gap_ratio)
            and (fill_parity["usd_gap_ratio"] <= args.max_fill_gap_ratio)
            and (fill_parity["usd_gap"] <= args.max_fill_gap_usd)
        )
        checks.append(
            GateResult(
                name="tracking.fill_parity",
                passed=fill_ok,
                metric=fill_parity,
                threshold={
                    "max_fill_gap_ratio": args.max_fill_gap_ratio,
                    "max_fill_gap_usd": args.max_fill_gap_usd,
                },
                reason=("entry fill parity within threshold" if fill_ok else "entry fill parity gap above threshold"),
            )
        )

        settlement_drift = _settlement_drift(conn, integrity_from_ts_ms, include_legacy)
        drift_ok = (settlement_drift["pnl_gap_ratio"] <= args.max_settlement_drift_ratio) and (
            settlement_drift["pnl_gap_usd"] <= args.max_settlement_drift_usd
        )
        checks.append(
            GateResult(
                name="tracking.settlement_pnl_drift",
                passed=drift_ok,
                metric=settlement_drift,
                threshold={
                    "max_settlement_drift_ratio": args.max_settlement_drift_ratio,
                    "max_settlement_drift_usd": args.max_settlement_drift_usd,
                },
                reason=(
                    "settlement vs market_close EXIT pnl drift within threshold"
                    if drift_ok
                    else "settlement vs market_close EXIT pnl drift above threshold"
                ),
            )
        )
    finally:
        conn.close()

    failed_checks = [check for check in checks if not check.passed]
    ok = len(failed_checks) == 0
    payload = {
        "ok": ok,
        "db_path": args.db,
        "generated_at_ms": now,
        "window": {
            "strategy_from_ts_ms": strategy_from_ts_ms,
            "integrity_from_ts_ms": integrity_from_ts_ms,
            "strategy_hours": max(args.strategy_hours, 1),
            "integrity_hours": max(args.integrity_hours, 1),
            "include_legacy_default": include_legacy,
        },
        "strategies_seen": sorted(strategy_rows.keys()),
        "checks": [check.to_json() for check in checks],
        "fail_count": len(failed_checks),
    }

    if args.json_pretty:
        rendered = json.dumps(payload, indent=2, sort_keys=True)
    else:
        rendered = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    status = "PASS" if ok else "FAIL"
    print(f"EVPOLY_ROLLOUT_GATE {status} {rendered}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
