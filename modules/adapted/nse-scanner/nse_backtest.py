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


"""Conservative EOD backtest for the scanner's long-only momentum setup.

This is a validation tool, not an order-execution system. Signals are formed
only at a completed close, entries are attempted during the next two sessions,
and a stop takes priority when a daily candle touches both stop and target.
"""


import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from nse_market_store import restore_prices

DB_PATH = "nse_scanner.db"


def _wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda values: np.dot(values, weights) / weights.sum(), raw=True)


def _hma(series, period=55):
    return _wma(2 * _wma(series, period // 2) - _wma(series, period), int(np.sqrt(period)))


def ensure_database():
    if Path(DB_PATH).exists():
        return
    from nse_loader import init_database

    init_database(DB_PATH)
    if not restore_prices(DB_PATH, min_days=1):
        msg = "No database or market_data snapshots found. Run the pipeline backfill first."
        raise RuntimeError(msg)


def load_prices(start, end):
    ensure_database()
    conn = sqlite3.connect(DB_PATH)
    try:
        query = "SELECT symbol, date, open, high, low, close, volume, delivery_pct FROM daily_prices WHERE close > 0"
        params = []
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY symbol, date"
        frame = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def simulate_symbol(symbol, frame, args):
    frame = frame.sort_values("date").copy()
    frame["ma50"] = frame["close"].rolling(50).mean()
    frame["ma200"] = frame["close"].rolling(200).mean()
    frame["avg_volume"] = frame["volume"].rolling(22).mean()
    frame["hma55"] = _hma(frame["close"], 55)
    frame["r3"] = frame["close"].pct_change(66)
    frame["r6"] = frame["close"].pct_change(126)
    frame["r12"] = frame["close"].pct_change(252)

    trades = []
    start_date = pd.Timestamp(args.start) if args.start else None
    end_date = pd.Timestamp(args.end) if args.end else None
    i = 253
    while i < len(frame) - 2:
        row = frame.iloc[i]
        if start_date is not None and row["date"] < start_date:
            i += 1
            continue
        if end_date is not None and row["date"] > end_date:
            break
        bullish = (
            row["r3"] > 0
            and row["r6"] > 0
            and row["r12"] > 0
            and row["close"] > row["ma200"]
            and row["ma50"] > row["ma200"]
            and row["close"] > row["hma55"]
            and row["hma55"] > frame.iloc[i - 1]["hma55"]
            and row["volume"] >= row["avg_volume"]
            and row["delivery_pct"] >= args.min_delivery
        )
        if not bullish or pd.isna(row["hma55"]):
            i += 1
            continue

        trigger = row["high"] * (1 + args.trigger_bps / 10_000)
        entry_idx = None
        for candidate_idx in range(i + 1, min(i + 3, len(frame))):
            candidate = frame.iloc[candidate_idx]
            if candidate["high"] >= trigger:
                entry_idx = candidate_idx
                entry = max(float(candidate["open"]), float(trigger))
                break
        if entry_idx is None:
            i += 1
            continue

        stop = float(row["hma55"] * (1 - args.stop_buffer_pct / 100))
        risk = entry - stop
        risk_pct = risk / entry * 100
        if risk <= 0 or risk_pct > args.max_risk_pct or risk_pct < args.min_risk_pct:
            i += 1
            continue

        target = entry + (risk * args.target_r)
        t1 = entry + risk
        t1_hit = False
        exit_idx = min(entry_idx + args.max_hold_days, len(frame) - 1)
        exit_price = float(frame.iloc[exit_idx]["close"])
        exit_reason = "TIME_STOP"

        for j in range(entry_idx, min(entry_idx + args.max_hold_days + 1, len(frame))):
            bar = frame.iloc[j]
            active_stop = entry if t1_hit else stop
            if bar["low"] <= active_stop:
                exit_idx, exit_price, exit_reason = j, active_stop, "STOP"
                break
            if bar["high"] >= target:
                exit_idx, exit_price, exit_reason = j, target, "TARGET_2R"
                break
            if bar["high"] >= t1:
                t1_hit = True

        entry_net = entry * (1 + args.cost_bps / 10_000)
        exit_net = exit_price * (1 - args.cost_bps / 10_000)
        trades.append(
            {
                "symbol": symbol,
                "signal_date": row["date"].date().isoformat(),
                "entry_date": frame.iloc[entry_idx]["date"].date().isoformat(),
                "exit_date": frame.iloc[exit_idx]["date"].date().isoformat(),
                "entry": round(entry, 2),
                "stop": round(stop, 2),
                "target": round(target, 2),
                "exit": round(exit_price, 2),
                "risk_pct": round(risk_pct, 2),
                "return_pct": round((exit_net / entry_net - 1) * 100, 2),
                "hold_days": int(exit_idx - entry_idx + 1),
                "exit_reason": exit_reason,
            }
        )
        i = exit_idx + 1
    return trades


def run_backtest(args):
    prices = load_prices(args.start, args.end)
    trades = []
    for symbol, group in prices.groupby("symbol"):
        trades.extend(simulate_symbol(str(symbol), group, args))
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return trades_df, {"trades": 0, "message": "No qualifying trades."}

    wins = trades_df[trades_df["return_pct"] > 0]
    losses = trades_df[trades_df["return_pct"] <= 0]
    summary = {
        "trades": len(trades_df),
        "win_rate_pct": round(len(wins) / len(trades_df) * 100, 2),
        "average_return_pct": round(float(trades_df["return_pct"].mean()), 2),
        "median_return_pct": round(float(trades_df["return_pct"].median()), 2),
        "average_win_pct": round(float(wins["return_pct"].mean()), 2) if not wins.empty else 0,
        "average_loss_pct": round(float(losses["return_pct"].mean()), 2) if not losses.empty else 0,
        "profit_factor": round(float(wins["return_pct"].sum() / abs(losses["return_pct"].sum())), 2)
        if not losses.empty and losses["return_pct"].sum()
        else None,
        "cost_bps_per_side": args.cost_bps,
        "assumption": "Daily stop has priority when stop and target are both touched.",
    }
    return trades_df, summary


def main():
    parser = argparse.ArgumentParser(description="Backtest NSE EOD momentum setup")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--output-dir", default="output/backtest")
    parser.add_argument("--trigger-bps", type=float, default=10)
    parser.add_argument("--cost-bps", type=float, default=20)
    parser.add_argument("--min-delivery", type=float, default=35)
    parser.add_argument("--stop-buffer-pct", type=float, default=3)
    parser.add_argument("--min-risk-pct", type=float, default=1)
    parser.add_argument("--max-risk-pct", type=float, default=7)
    parser.add_argument("--target-r", type=float, default=2)
    parser.add_argument("--max-hold-days", type=int, default=20)
    args = parser.parse_args()

    trades, summary = run_backtest(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output_dir / "trades.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
