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
"""
watchdog_check.py
Schedule-aware decision logic for the watchdog workflow: should we trigger a
recovery scan right now, or stay quiet?

Why this exists
---------------
The original watchdog fired `gh workflow run scan.yml` on EVERY 15-min tick
while latest_scan.json was >45 min old. Because scan.yml's concurrency group
queues rather than cancels, one drifted scan produced 1 scheduled run plus
3-4 queued watchdog-triggered duplicates (10-12 scan commits/day vs the
intended 2 — see CHANGELOG 1.3.3). This script fixes that with three checks:

  1. Is the scan actually late? (next_expected_utc + grace, not a raw
     commit-age threshold — a scan is only "late" past its NEXT window.)
  2. Is a scan run already queued or in-flight? (`gh run list` — never
     trigger a duplicate onto the queue.)
  3. Did WE already trigger one recently? (marker file with a cooldown —
     covers the queued-but-not-yet-started gap that `gh run list` misses.)

Exit codes:
  0  healthy (or stale but a run is already active/recent) — do not trigger
  10 stale AND safe to trigger — the workflow should run scan.yml
     (deliberately NOT 2: argparse exits 2 on bad arguments, and the
     caller must never confuse "bad invocation" with "trigger")
  1  invalid arguments / corrupt marker (safe to continue; caller decides)

The workflow consumes the decision; this module contains no network I/O
itself (the caller passes in run state), so it is fully unit-testable.

Usage (from watchdog.yml):
    python scripts/watchdog_check.py \
      --latest ../frontend/public/data/latest_scan.json \
      --status ../frontend/public/data/scan_status.json \
      --marker ../frontend/public/data/.watchdog_last_trigger \
      --run-state "$RUN_STATE" \
      --grace-min 30 --cooldown-min 45
  where RUN_STATE is one of: none | queued | in_progress | (anything else
  treated as in_progress). The workflow computes it via `gh run list`.
"""

import argparse
import json
import os
import sys
from typing import List, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPTS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from scan_schedule import next_scheduled_window  # noqa: E402

# Run states the workflow derives from `gh run list` for scan.yml.
RUN_NONE = "none"
RUN_QUEUED = "queued"
RUN_IN_PROGRESS = "in_progress"

# Default: how long after the next scheduled window we call the scan late,
# and how long the trigger-marker cooldown lasts. The cooldown must cover
# the worst-case gap between "trigger fired" and the run becoming visible
# in `gh run list` (queue latency during runner-scarcity peaks), plus the
# scan runtime we do not want to stack on top of.
DEFAULT_GRACE_MIN = 30
DEFAULT_COOLDOWN_MIN = 45


def parse_iso_utc(s: str) -> datetime.datetime | None:
    try:
        dt = datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(datetime.UTC)


def load_json(path: str) -> dict | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def read_marker(path: str) -> datetime.datetime | None:
    """Last time the watchdog itself triggered a scan (ISO string in file)."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            raw = f.read().strip()
        return parse_iso_utc(raw)
    except OSError:
        return None


def write_marker(path: str, now: datetime.datetime) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(now.isoformat())
    except OSError:
        # Best-effort marker: if we can't write it, worst case is one extra
        # trigger per tick — same as pre-1.3.3 behaviour, never worse.
        pass


def is_scan_late(
    status: dict | None,
    latest: dict | None,
    now: datetime.datetime,
    grace_min: int,
) -> bool:
    """
    True when the next scheduled window is in the past by more than grace_min
    (primary signal — weekend/holiday aware) OR, when no status exists,
    generated_at is older than the same threshold.
    """
    grace = datetime.timedelta(minutes=grace_min)
    next_expected = None
    if status:
        next_expected = parse_iso_utc(status.get("next_expected_utc") or "")
    if next_expected is None:
        generated_at = parse_iso_utc((latest or {}).get("generated_at") or "")
        if generated_at is None:
            # No data at all: treat as late so the first-ever scan gets fetched.
            return True
        next_expected = next_scheduled_window(generated_at) or (generated_at + datetime.timedelta(hours=12))
    return now > next_expected + grace


def should_trigger(
    *,
    run_state: str,
    latest: dict | None,
    status: dict | None,
    marker_dt: datetime.datetime | None,
    now: datetime.datetime,
    grace_min: int = DEFAULT_GRACE_MIN,
    cooldown_min: int = DEFAULT_COOLDOWN_MIN,
) -> tuple[bool, str]:
    """
    The decision. Returns (trigger: bool, reason: str).

    Order matters: the cheap "already covered" checks come first so an
    in-flight scan always wins over staleness.
    """
    if run_state in (RUN_QUEUED, RUN_IN_PROGRESS):
        return False, f"scan already {run_state} — not triggering a duplicate"

    if marker_dt is not None:
        cooldown = datetime.timedelta(minutes=cooldown_min)
        if now - marker_dt < cooldown:
            remaining = int((cooldown - (now - marker_dt)).total_seconds() // 60)
            return False, f"watchdog triggered a scan {remaining} min ago (cooldown active)"

    if not is_scan_late(status, latest, now, grace_min):
        return False, "scan fresh (within next_expected window + grace)"

    return True, "scan late past next window + grace, no run queued/in-progress, cooldown expired"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Watchdog: decide whether to trigger a recovery scan.")
    p.add_argument("--latest", required=True, help="Path to latest_scan.json")
    p.add_argument("--status", default=None, help="Path to scan_status.json (best-effort)")
    p.add_argument("--marker", required=True, help="Path to the last-trigger marker file")
    p.add_argument(
        "--run-state",
        default=RUN_NONE,
        choices=[RUN_NONE, RUN_QUEUED, RUN_IN_PROGRESS, "unknown"],
        help="Current scan.yml run state (from `gh run list` in the workflow)",
    )
    p.add_argument("--grace-min", type=int, default=DEFAULT_GRACE_MIN)
    p.add_argument("--cooldown-min", type=int, default=DEFAULT_COOLDOWN_MIN)
    p.add_argument("--now", default=None, help="Override 'now' (ISO); for tests.")
    p.add_argument(
        "--age-min",
        type=int,
        default=None,
        help="latest_scan.json commit age in minutes (informational, echoed to output)",
    )
    args = p.parse_args(argv)

    if args.now:
        now = parse_iso_utc(args.now)
        if now is None:
            print(f"::error::unparseable --now value: {args.now!r}", file=sys.stderr)
            return 1
    else:
        now = datetime.datetime.now(datetime.UTC)

    latest = load_json(args.latest)
    status = load_json(args.status) if args.status else None
    marker_dt = read_marker(args.marker)

    trigger, reason = should_trigger(
        run_state=args.run_state,
        latest=latest,
        status=status,
        marker_dt=marker_dt,
        now=now,
        grace_min=args.grace_min,
        cooldown_min=args.cooldown_min,
    )

    age = f" age_min={args.age_min}" if args.age_min is not None else ""
    if trigger:
        write_marker(args.marker, now)
        print(f"TRIGGER{age}: {reason}")
        return 10
    print(f"SKIP{age}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
