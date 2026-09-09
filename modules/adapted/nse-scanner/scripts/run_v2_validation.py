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


"""Run Sprint 7 point-in-time backtest and validation reports."""

import argparse
import json
from pathlib import Path

from v2.backtest import run_point_in_time_backtest
from v2.database import V2Database
from v2.performance import summarize_performance, trades_frame
from v2.walk_forward import anchored_walk_forward, score_sensitivity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--output", default="output/v2_validation")
    parser.add_argument("--minimum-score", type=float, default=70.0)
    parser.add_argument("--warmup", type=int, default=120)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--walk-forward", action="store_true")
    args = parser.parse_args()

    prices = V2Database(args.db).load_prices(min_sessions=args.warmup + 1)
    if prices.empty:
        msg = "No usable price history for validation"
        raise RuntimeError(msg)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    trades = run_point_in_time_backtest(
        prices,
        minimum_score=args.minimum_score,
        warmup_sessions=args.warmup,
        max_positions=args.max_positions,
    )
    report = summarize_performance(trades)
    trades_frame(trades).to_csv(output / "trades.csv", index=False)
    (output / "performance.json").write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")

    sensitivity = score_sensitivity(
        prices,
        warmup_sessions=args.warmup,
        max_positions=args.max_positions,
    )
    (output / "score_sensitivity.json").write_text(json.dumps(sensitivity, indent=2, default=str), encoding="utf-8")

    if args.walk_forward:
        rows = anchored_walk_forward(
            prices,
            warmup_sessions=args.warmup,
            max_positions=args.max_positions,
        )
        (output / "walk_forward.json").write_text(
            json.dumps([row.to_dict() for row in rows], indent=2), encoding="utf-8"
        )

    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
