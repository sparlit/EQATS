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


"""
Research validation runner for the intraday selector.

Runs the selector against forced-arm baselines and reports whether higher ML
scores actually map to better realized P&L. This is deliberately small and
walk-forward: it calls the same backend runner used by the API.

Usage:
    ALGO_CACHE_ONLY=1 venv/bin/python backend/research_validate.py --start 2026-04-01 --end 2026-05-31 \
      --symbols HDFCBANK ICICIBANK RELIANCE SBIN TCS INFY AXISBANK LT TATAMOTORS SUNPHARMA \
      --capital 500000
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from backtest import run
from risk import RiskConfig
from strategies import STRATEGY_REGISTRY

DEFAULT_SYMBOLS = [
    "HDFCBANK",
    "ICICIBANK",
    "RELIANCE",
    "SBIN",
    "TCS",
    "INFY",
    "AXISBANK",
    "LT",
    "TATAMOTORS",
    "SUNPHARMA",
]


def _args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--capital", type=float, default=500_000)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--max-loss-pct", type=float, default=3.0)
    p.add_argument("--interval", default="5m")
    p.add_argument("--history-days", type=int, default=180)
    p.add_argument(
        "--allow-network",
        action="store_true",
        help="Allow Upstox/Yahoo fetches for missing cache rows. Default is cache-only.",
    )
    return p.parse_args()


def _clean(v):
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _summary(name, result):
    s = result["summary"]
    return {
        "name": name,
        "pnl": s.get("pnl", 0.0),
        "return_pct": s.get("return_pct", 0.0),
        "trades": s.get("total_trades", 0),
        "win_rate": s.get("win_rate", 0.0),
        "profit_factor": s.get("profit_factor", 0.0),
        "max_drawdown": s.get("max_drawdown", 0.0),
        "sharpe": s.get("sharpe", 0.0),
        "expectancy": s.get("expectancy", 0.0),
    }


def _calibration(result):
    trade_pnl = {(t.date, t.symbol.replace(".NS", "")): t.pnl for t in result["trades"]}
    rows = []
    for d in result.get("day_regimes", []):
        strategy = d.get("strategy", "")
        if strategy == "No Trade":
            continue
        score_map = d.get("score", {}) or {}
        exp_map = d.get("expectancy", {}) or {}
        arm = None
        for arm_id, meta in STRATEGY_REGISTRY.items():
            if meta["name"] == strategy:
                arm = arm_id
                break
        if not arm:
            continue
        key = (d["date"], d["symbol"])
        rows.append(
            {
                "score": float(score_map.get(arm, 0.0)),
                "expectancy": float(exp_map.get(arm, 0.0)),
                "pnl": float(trade_pnl.get(key, 0.0)),
            }
        )
    if not rows:
        return []

    rows = sorted(rows, key=lambda x: x["score"])
    buckets = []
    bucket_count = min(5, len(rows))
    for i in range(bucket_count):
        lo = round(i * len(rows) / bucket_count)
        hi = round((i + 1) * len(rows) / bucket_count)
        part = rows[lo:hi]
        if not part:
            continue
        wins = [r for r in part if r["pnl"] > 0]
        buckets.append(
            {
                "bucket": i + 1,
                "n": len(part),
                "score_min": round(part[0]["score"], 4),
                "score_max": round(part[-1]["score"], 4),
                "avg_score": round(sum(r["score"] for r in part) / len(part), 4),
                "avg_expectancy_r": round(sum(r["expectancy"] for r in part) / len(part), 4),
                "avg_pnl": round(sum(r["pnl"] for r in part) / len(part), 2),
                "win_rate": round(len(wins) / len(part) * 100, 1),
            }
        )
    return buckets


def main():
    args = _args()
    if not args.allow_network:
        os.environ["ALGO_CACHE_ONLY"] = "1"

    symbols = [s if s.endswith(".NS") else f"{s}.NS" for s in args.symbols]
    cfg = RiskConfig(
        risk_per_trade_pct=args.risk_pct,
        max_daily_loss_pct=args.max_loss_pct,
    )

    selector = run(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        capital=args.capital,
        risk_config=cfg,
        interval=args.interval,
        save_to_db=False,
        history_days=args.history_days,
    )

    baselines = []
    for arm in STRATEGY_REGISTRY:
        result = run(
            symbols=symbols,
            start_date=args.start,
            end_date=args.end,
            capital=args.capital,
            risk_config=cfg,
            interval=args.interval,
            save_to_db=False,
            force_strategy=arm,
            history_days=args.history_days,
        )
        baselines.append(_summary(f"always_{arm}", result))

    by_strategy = defaultdict(float)
    for t in selector["trades"]:
        by_strategy[t.strategy] += t.pnl

    report = {
        "range": {"start": args.start, "end": args.end},
        "symbols": [s.replace(".NS", "") for s in symbols],
        "selector": _summary("selector", selector),
        "baselines": baselines,
        "selector_pnl_by_strategy": {k: round(v, 2) for k, v in sorted(by_strategy.items())},
        "score_calibration": _calibration(selector),
    }
    print(json.dumps(_clean(report), indent=2))


if __name__ == "__main__":
    main()
