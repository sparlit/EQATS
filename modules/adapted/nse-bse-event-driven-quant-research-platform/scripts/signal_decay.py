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


"""Signal decay analysis: compare predicted vs actual returns by time since signal.

Usage:
    python scripts/signal_decay.py [--min-settled 10]
"""


import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlalchemy as sa
from indian_quant.config.connections import get_engine


def signal_decay_analysis(engine, min_settled: int = 10) -> dict:
    """Analyze signal decay: how returns change over holding periods."""
    with engine.connect() as conn:
        # Get all settled trades with their holding periods
        rows = (
            conn.execute(
                sa.text("""
            SELECT
                symbol, entry_date, exit_date, days_held,
                return_pct, return_bps, realized_net_bps,
                horizon_label, exit_reason
            FROM paper_signals
            WHERE status = 'SETTLED'
              AND realized_net_bps IS NOT NULL
              AND days_held IS NOT NULL
            ORDER BY entry_date
        """)
            )
            .mappings()
            .fetchall()
        )

    if len(rows) < min_settled:
        return {"error": f"Need >= {min_settled} settled trades, have {len(rows)}"}

    # Group by days_held buckets
    buckets = {}
    for r in rows:
        dh = r["days_held"] or 0
        if dh <= 1:
            bucket = "1d"
        elif dh <= 5:
            bucket = "2-5d"
        elif dh <= 10:
            bucket = "6-10d"
        elif dh <= 15:
            bucket = "11-15d"
        else:
            bucket = "16d+"
        if bucket not in buckets:
            buckets[bucket] = {"returns": [], "nets": [], "wins": 0, "total": 0}
        buckets[bucket]["returns"].append(r["return_pct"] or 0)
        buckets[bucket]["nets"].append(r["realized_net_bps"] or 0)
        buckets[bucket]["total"] += 1
        if (r["realized_net_bps"] or 0) > 0:
            buckets[bucket]["wins"] += 1

    # Compute summary stats per bucket
    result = {}
    for bucket, data in sorted(buckets.items()):
        n = data["total"]
        avg_ret = sum(data["returns"]) / n
        avg_net = sum(data["nets"]) / n
        win_rate = data["wins"] / n * 100
        result[bucket] = {
            "count": n,
            "avg_return_pct": round(avg_ret, 2),
            "avg_net_bps": round(avg_net, 1),
            "win_rate_pct": round(win_rate, 1),
        }

    # Overall stats
    all_nets = [r["realized_net_bps"] or 0 for r in rows]
    all_rets = [r["return_pct"] or 0 for r in rows]
    result["overall"] = {
        "count": len(rows),
        "avg_return_pct": round(sum(all_rets) / len(all_rets), 2),
        "avg_net_bps": round(sum(all_nets) / len(all_nets), 1),
        "win_rate_pct": round(sum(1 for n in all_nets if n > 0) / len(all_nets) * 100, 1),
    }

    # Exit reason breakdown
    reasons = {}
    for r in rows:
        reason = r["exit_reason"] or "UNKNOWN"
        if reason not in reasons:
            reasons[reason] = {"count": 0, "nets": []}
        reasons[reason]["count"] += 1
        reasons[reason]["nets"].append(r["realized_net_bps"] or 0)

    result["by_exit_reason"] = {
        k: {"count": v["count"], "avg_net_bps": round(sum(v["nets"]) / len(v["nets"]), 1)}
        for k, v in sorted(reasons.items())
    }

    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--min-settled", type=int, default=10)
    args = parser.parse_args()

    engine = get_engine()
    result = signal_decay_analysis(engine, args.min_settled)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
