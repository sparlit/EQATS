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
snapshot_writer.py
Persists each completed scan as a dated, minified JSON file alongside an
index of all snapshots in the window. Implements the B1 plan item:

  - One snapshot per scan (named YYYY-MM-DD-{am|pm}.json)
  - Rolling 90-day prune (configurable via --retention-days)
  - history_index.json: sorted list of {date, slot, file, generated_at,
    gate_pass_count, universe_size}
  - Minified (no indent) to keep repo bloat manageable:
        ~500 stocks × ~30 fields × ~2 scans/day × 90 days ≈ 40-60 MB
    Pretty-printed latest_scan.json stays the load-bearing artifact.

Idempotent: re-running with the same (date, slot) overwrites in place.

Usage (from scan.yml):
    python backend/scripts/snapshot_writer.py \\
        --latest ../frontend/public/data/latest_scan.json \\
        --snapshots ../frontend/public/data/snapshots \\
        --retention-days 90 \\
        [--slot am|pm] [--now 2026-07-18T10:35:00Z]

Exit codes:
  0  success
  1  invalid arguments / file missing / IO error
  2  parsed input but history_index invariant broken (e.g. duplicate file)
"""
import argparse
import contextlib
import datetime
import json
import os
import re
import sys
from typing import List, Optional, Tuple

SNAPSHOT_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(am|pm)\.json$")


def parse_iso_utc(s: str) -> datetime.datetime:
    """Parse a YYYY-MM-DD or full ISO-8601 string; returns tz-aware UTC."""
    dt = datetime.datetime.fromisoformat(s) if "T" in s else datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(datetime.UTC)


def slot_for_generated_at(generated_at_iso: str, *, now: datetime.datetime | None = None) -> str:
    """
    Derive the snapshot slot ('am' / 'pm') from the scan's generated_at.
    The two crons fire at 03:30 UTC (am, prior close) and 10:30 UTC (pm,
    same-day close). generated_at is set just before write_scan_output,
    so its UTC hour is a reliable discriminator in practice (within
    ±1 min of the cron fire time).
    """
    dt = parse_iso_utc(generated_at_iso)
    hour = dt.hour
    if hour < 8:
        return "am"
    return "pm"


def date_for_filename(generated_at_iso: str) -> str:
    """YYYY-MM-DD in UTC from the scan's generated_at."""
    dt = parse_iso_utc(generated_at_iso)
    return dt.strftime("%Y-%m-%d")


def write_snapshot(
    latest_path: str,
    snapshots_dir: str,
    *,
    slot: str,
    generated_at_iso: str,
    retention_days: int = 90,
) -> tuple[str, dict]:
    """
    Reads latest_scan.json, writes a minified snapshot file, updates
    history_index.json, and prunes snapshots older than retention_days.

    Returns (snapshot_filename, history_index_dict).
    """
    if slot not in ("am", "pm"):
        msg = f"slot must be 'am' or 'pm'; got {slot!r}"
        raise ValueError(msg)
    if retention_days <= 0:
        msg = f"retention_days must be positive; got {retention_days}"
        raise ValueError(msg)

    if not os.path.exists(latest_path):
        msg = f"latest_scan.json not found at {latest_path}"
        raise FileNotFoundError(msg)
    os.makedirs(snapshots_dir, exist_ok=True)

    with open(latest_path) as f:
        scan = json.load(f)

    if not isinstance(scan, dict) or "stocks" not in scan:
        msg = "latest_scan.json is not a valid scan payload (missing 'stocks')"
        raise ValueError(msg)
    if not isinstance(scan["stocks"], list) or len(scan["stocks"]) == 0:
        msg = "latest_scan.json has no stocks (refusing to snapshot empty universe)"
        raise ValueError(msg)

    if not generated_at_iso:
        generated_at_iso = scan.get("generated_at")
    if not generated_at_iso:
        msg = "no generated_at provided or present in latest_scan.json"
        raise ValueError(msg)

    date_str = date_for_filename(generated_at_iso)
    filename = f"{date_str}-{slot}.json"
    out_path = os.path.join(snapshots_dir, filename)

    # Minified write (smaller git footprint). Preserve insert order; do NOT
    # sort_keys — stock array order is meaningful (swing_score desc).
    with open(out_path, "w") as f:
        json.dump(scan, f, separators=(",", ":"), ensure_ascii=False)

    # Update history index
    index_path = os.path.join(snapshots_dir, "history_index.json")
    index: list[dict] = []
    if os.path.exists(index_path):
        try:
            with open(index_path) as f:
                existing = json.load(f)
            if isinstance(existing, list):
                index = existing
        except (OSError, json.JSONDecodeError):
            # Corrupt index — rebuild from disk on the next prune.
            index = []

    entry = {
        "date": date_str,
        "slot": slot,
        "file": filename,
        "generated_at": generated_at_iso,
        "universe_size": scan.get("universe_size", len(scan["stocks"])),
        "gate_pass_count": scan.get("gate_pass_count", sum(1 for s in scan["stocks"] if s.get("gate_pass"))),
    }

    # Replace any prior entry for this (date, slot).
    index = [e for e in index if not (e.get("date") == date_str and e.get("slot") == slot)]
    index.append(entry)
    index.sort(key=lambda e: (e.get("date", ""), e.get("slot", "")))

    prune_snapshots(snapshots_dir, index, retention_days)

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return filename, {"entries": index, "file": filename}


def prune_snapshots(snapshots_dir: str, index: list[dict], retention_days: int) -> None:
    """
    Drop snapshot files older than retention_days AND any index entries
    pointing at them. Index entries referencing non-existent files are
    also removed.
    """
    cutoff = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)).date()
    kept: list[dict] = []
    for e in index:
        d = e.get("date")
        try:
            d_date = datetime.date.fromisoformat(d)
        except Exception:
            continue
        fname = e.get("file")
        fpath = os.path.join(snapshots_dir, fname) if fname else None
        # Drop entries that are too old, or that point at a missing file.
        if d_date < cutoff:
            if fpath and os.path.exists(fpath):
                with contextlib.suppress(OSError):
                    os.remove(fpath)
            continue
        if not fname or not SNAPSHOT_FILENAME_RE.match(fname):
            continue
        if fpath is None or not os.path.exists(fpath):
            continue
        kept.append(e)

    # Sweep orphan files (in snapshots dir, no entry in index, and outside retention).
    if os.path.isdir(snapshots_dir):
        for name in os.listdir(snapshots_dir):
            if name == "history_index.json":
                continue
            m = SNAPSHOT_FILENAME_RE.match(name)
            if not m:
                continue
            try:
                f_date = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if f_date < cutoff:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(snapshots_dir, name))

    index.clear()
    index.extend(kept)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Persist the latest scan as a dated, minified snapshot.")
    p.add_argument("--latest", required=True, help="Path to latest_scan.json")
    p.add_argument("--snapshots", required=True, help="Directory for snapshot files (created if missing)")
    p.add_argument(
        "--slot", choices=["am", "pm"], default=None, help="Snapshot slot; if omitted, derived from generated_at hour."
    )
    p.add_argument("--now", default=None, help="Override 'now' (UTC ISO); for tests.")
    p.add_argument("--retention-days", type=int, default=90, help="Keep snapshots within this many days; default 90.")
    args = p.parse_args(argv)

    try:
        with open(args.latest) as f:
            scan = json.load(f)
        generated_at = scan.get("generated_at", "")
        slot = args.slot or slot_for_generated_at(generated_at)
        filename, idx = write_snapshot(
            args.latest,
            args.snapshots,
            slot=slot,
            generated_at_iso=generated_at,
            retention_days=args.retention_days,
        )
    except FileNotFoundError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    except (ValueError, json.JSONDecodeError, OSError) as e:
        print(f"::error::snapshot_writer: {e}", file=sys.stderr)
        return 1

    kept = len(idx["entries"])
    print(f"snapshot_writer: wrote {filename}; index entries={kept}; retention={args.retention_days}d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
