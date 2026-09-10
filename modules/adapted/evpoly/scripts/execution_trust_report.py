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
import argparse
import json
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Dict, List, Optional


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    k = (len(values) - 1) * p
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def fmt(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.2f}"


def load_execution_timing(events_path: Path, since_ms: int) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if not events_path.exists():
        return latest
    with events_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            ts_ms = obj.get("ts_ms")
            if not isinstance(ts_ms, (int, float)) or ts_ms < since_ms:
                continue
            if obj.get("kind") != "entry_execution_timing":
                continue
            payload = obj.get("payload") or {}
            rid = str(payload.get("request_id") or "")
            if not rid:
                continue
            prev = latest.get(rid)
            if prev is None or ts_ms >= prev.get("_ts", -1):
                payload["_ts"] = ts_ms
                latest[rid] = payload
    return latest


def load_ack_metrics(db_path: Path, since_ms: int):
    ack_ms: list[float] = []
    api_post_ms: list[float] = []
    if not db_path.exists():
        return ack_ms, api_post_ms
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts_ms, reason
        FROM trade_events
        WHERE event_type='ENTRY_ACK' AND ts_ms>=?
        """,
        (since_ms,),
    )
    for row in cur.fetchall():
        reason = row["reason"]
        if not reason:
            continue
        try:
            meta = json.loads(reason)
        except Exception:
            continue
        if isinstance(meta.get("order_ack_latency_ms"), (int, float)):
            ack_ms.append(float(meta["order_ack_latency_ms"]))
        if isinstance(meta.get("api_post_order_ms"), (int, float)):
            api_post_ms.append(float(meta["api_post_order_ms"]))
    conn.close()
    return ack_ms, api_post_ms


def main():
    parser = argparse.ArgumentParser(description="Execution trust metrics report")
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument("--events", default="events.jsonl")
    parser.add_argument("--db", default="tracking.db")
    args = parser.parse_args()

    now_ms = int(time.time() * 1000)
    since_ms = now_ms - int(args.hours * 3600 * 1000)

    timing_by_req = load_execution_timing(Path(args.events), since_ms)
    queue_wait = []
    decision_to_submit = []
    for payload in timing_by_req.values():
        q = payload.get("queue_wait_ms")
        if isinstance(q, (int, float)):
            queue_wait.append(float(q))
        d = payload.get("decision_to_submit_ms")
        if isinstance(d, (int, float)):
            decision_to_submit.append(float(d))

    ack_ms, api_post_ms = load_ack_metrics(Path(args.db), since_ms)

    print(f"Window: last {args.hours}h")
    print("- entry_execution_timing rows:", len(timing_by_req))
    print(
        f"- queue_wait_ms: n={len(queue_wait)} p50={fmt(percentile(queue_wait, 0.50))} p95={fmt(percentile(queue_wait, 0.95))}"
    )
    print(
        f"- decision_to_submit_ms: n={len(decision_to_submit)} p50={fmt(percentile(decision_to_submit, 0.50))} p95={fmt(percentile(decision_to_submit, 0.95))}"
    )
    print(f"- ack_ms: n={len(ack_ms)} p50={fmt(percentile(ack_ms, 0.50))} p95={fmt(percentile(ack_ms, 0.95))}")
    print(
        f"- api_post_order_ms: n={len(api_post_ms)} p50={fmt(percentile(api_post_ms, 0.50))} p95={fmt(percentile(api_post_ms, 0.95))}"
    )


if __name__ == "__main__":
    main()
