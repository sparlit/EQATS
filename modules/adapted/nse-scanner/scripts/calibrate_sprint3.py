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


"""Calibrate Sprint 3 selection rules against repository market snapshots.

This is a diagnostic walk-through, not a performance backtest. It measures
candidate frequency, setup mix, score distribution, plan rejection reasons and
trade-plan geometry without using future prices.
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd
from nse_loader import init_database
from nse_market_store import restore_prices
from v2.candidates import evaluate_candidate
from v2.database import V2Database


def _regime_proxy(prices: pd.DataFrame, trade_date: pd.Timestamp) -> str:
    day = prices[prices["trade_date"] == trade_date]
    if day.empty:
        return "NEUTRAL"
    history = prices[prices["trade_date"] <= trade_date].copy()
    history["sma50"] = history.groupby("symbol")["close"].transform(lambda s: s.rolling(50).mean())
    latest = history.groupby("symbol", as_index=False).tail(1).dropna(subset=["sma50"])
    if latest.empty:
        return "NEUTRAL"
    breadth = float((latest["close"] > latest["sma50"]).mean() * 100)
    if breadth >= 60:
        return "BULL"
    if breadth <= 35:
        return "BEAR"
    return "NEUTRAL"


def run(db_path: Path, output_dir: Path, warmup: int = 120, stride: int = 5) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    init_database(str(db_path))
    restore_prices(db_path, min_days=1)
    prices = V2Database(db_path).load_prices()
    dates = sorted(prices["trade_date"].drop_duplicates())

    records: list[dict] = []
    for idx in range(warmup, len(dates), stride):
        as_of = dates[idx]
        regime = _regime_proxy(prices, as_of)
        history = prices[prices["trade_date"] <= as_of]
        for symbol, frame in history.groupby("symbol"):
            if len(frame) < 60:
                continue
            candidate = evaluate_candidate(symbol, frame.tail(300), regime)
            row = candidate.to_dict()
            row["regime"] = regime
            records.append(row)

    frame = pd.DataFrame(records)
    if frame.empty:
        msg = "Calibration produced no candidate observations"
        raise RuntimeError(msg)

    selected = frame[frame["selected"]]
    reason_counter = Counter(reason for reasons in frame["reasons_against"] for reason in reasons)
    result = {
        "status": "PASS",
        "observations": len(frame),
        "selected": len(selected),
        "selection_rate_pct": round(100.0 * len(selected) / len(frame), 3),
        "selected_per_scan_median": float(selected.groupby("trade_date").size().median())
        if not selected.empty
        else 0.0,
        "setup_mix": selected["setup"].value_counts().to_dict(),
        "score_quantiles": frame["score"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_dict(),
        "selected_score_quantiles": selected["score"].quantile([0.1, 0.5, 0.9]).round(2).to_dict()
        if not selected.empty
        else {},
        "median_stop_pct": float(((selected["entry"] - selected["stop"]) / selected["entry"] * 100).median())
        if not selected.empty
        else 0.0,
        "median_rr_t1": float(selected["reward_risk_t1"].median()) if not selected.empty else 0.0,
        "median_rr_t2": float(selected["reward_risk_t2"].median()) if not selected.empty else 0.0,
        "top_rejection_reasons": reason_counter.most_common(15),
        "parameter_recommendation": {
            "minimum_score": 70.0,
            "decision": "retain_pending_outcome_backtest",
            "reason": "Sprint 3 calibration measures signal density and plan geometry only; profitability thresholds require Sprint 7 point-in-time testing.",
        },
    }
    frame.to_json(output_dir / "sprint3_calibration_observations.jsonl", orient="records", lines=True)
    (output_dir / "sprint3_calibration_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="output/v2_calibration/sprint3.db")
    parser.add_argument("--output", default="output/v2_calibration")
    parser.add_argument("--stride", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.db), Path(args.output), stride=args.stride), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
