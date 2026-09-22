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
Out-of-Sample Forward Test
──────────────────────────
Splits available trading days into:
  - IN-SAMPLE  (train period): Mar 10–17  (used for model training)
  - OUT-OF-SAMPLE (test period): Mar 18–20 (unseen by models)

Runs the full backtest pipeline on OOS days only, then compares
metrics against the in-sample period to detect overfitting.

Usage:
  python scripts/forward_test.py
  python scripts/forward_test.py --risk high
  python scripts/forward_test.py --split 2026-03-18   # custom split date
"""

import argparse
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

import numpy as np
import pandas as pd
from data.news_sentiment import NewsSentimentEngine
from features.option_chain_features import OptionChainFeatureEngine
from models.predict import Predictor
from models.rl_exit_agent import RLExitAgent
from models.strategy_models import StrategyPredictor
from scripts.tick_replay_backtest import apply_risk_profile, get_available_days, replay_day
from strategy.regime_detector import RegimeDetector
from strategy.vol_surface import VolSurfaceModel
from utils.logger import get_logger

from config.risk_profiles import _PROFILE, RiskLevel, apply_risk_profile
from database.db import read_sql

logger = get_logger("forward_test")


def compute_metrics(trades: list, label: str) -> dict:
    """Compute standardised performance metrics from a trade list."""
    if not trades:
        return {"label": label, "trades": 0, "pnl": 0, "wr": 0, "rr": 0, "max_dd": 0, "avg_per_day": 0}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Max drawdown (equity curve)
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    max_dd = float(dd.min())

    days = len({str(t["entry_time"])[:10] for t in trades})

    return {
        "label": label,
        "trades": len(trades),
        "days": days,
        "pnl": round(sum(pnls), 2),
        "avg_per_day": round(sum(pnls) / max(days, 1), 2),
        "wr": round(len(wins) / len(pnls) * 100, 1),
        "avg_win": round(np.mean(wins), 2) if wins else 0,
        "avg_loss": round(np.mean(losses), 2) if losses else 0,
        "rr": round(abs(np.mean(wins) / np.mean(losses)), 2) if wins and losses else 0,
        "max_dd": round(max_dd, 2),
        "rl_exit_wr": round(
            sum(1 for t in trades if t.get("result") == "RL_EXIT" and t["pnl"] > 0)
            / max(sum(1 for t in trades if t.get("result") == "RL_EXIT"), 1)
            * 100,
            1,
        ),
    }


def print_comparison(is_metrics: dict, oos_metrics: dict):
    """Print side-by-side in-sample vs out-of-sample comparison."""
    print("\n" + "=" * 65)
    print("  IN-SAMPLE vs OUT-OF-SAMPLE COMPARISON")
    print("=" * 65)
    rows = [
        ("Days replayed", is_metrics["days"], oos_metrics["days"]),
        ("Total trades", is_metrics["trades"], oos_metrics["trades"]),
        ("Total P&L", f"₹{is_metrics['pnl']:+,.0f}", f"₹{oos_metrics['pnl']:+,.0f}"),
        ("Avg P&L / day", f"₹{is_metrics['avg_per_day']:+,.0f}", f"₹{oos_metrics['avg_per_day']:+,.0f}"),
        ("Win rate", f"{is_metrics['wr']}%", f"{oos_metrics['wr']}%"),
        ("Avg winner", f"₹{is_metrics['avg_win']:+,.0f}", f"₹{oos_metrics['avg_win']:+,.0f}"),
        ("Avg loser", f"₹{is_metrics['avg_loss']:+,.0f}", f"₹{oos_metrics['avg_loss']:+,.0f}"),
        ("Risk-Reward", is_metrics["rr"], oos_metrics["rr"]),
        ("Max drawdown", f"₹{is_metrics['max_dd']:,.0f}", f"₹{oos_metrics['max_dd']:,.0f}"),
        ("RL_EXIT win rate", f"{is_metrics['rl_exit_wr']}%", f"{oos_metrics['rl_exit_wr']}%"),
    ]
    print(f"  {'Metric':<22} {'IN-SAMPLE':>18} {'OUT-OF-SAMPLE':>18}")
    print(f"  {'-' * 22} {'-' * 18} {'-' * 18}")
    for row in rows:
        print(f"  {row[0]:<22} {row[1]!s:>18} {row[2]!s:>18}")
    print("=" * 65)

    # Overfitting signal
    wr_diff = oos_metrics["wr"] - is_metrics["wr"]
    pnl_ratio = oos_metrics["avg_per_day"] / max(abs(is_metrics["avg_per_day"]), 1)
    print(f"\n  WR delta (OOS - IS): {wr_diff:+.1f}%  ", end="")
    if abs(wr_diff) < 10:
        print("✅ Consistent (no overfitting signal)")
    elif wr_diff < -15:
        print("⚠️  OOS win rate significantly lower — possible overfit")
    else:
        print("ℹ️  OOS performing differently from IS")

    print(f"  P&L ratio (OOS/IS daily): {pnl_ratio:.2f}x  ", end="")
    if pnl_ratio >= 0.5:
        print("✅ OOS holds up well")
    else:
        print("⚠️  OOS P&L much lower than IS")
    print()


def main():
    parser = argparse.ArgumentParser(description="Out-of-sample forward test")
    parser.add_argument("--risk", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--split", default="2026-03-18", help="First OOS date (everything before = in-sample)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    risk_level = RiskLevel(args.risk)
    apply_risk_profile(risk_level)
    split_date = datetime.strptime(args.split, "%Y-%m-%d").date()

    print("=" * 65)
    print(f"  OUT-OF-SAMPLE FORWARD TEST  [{_PROFILE.name.upper()} RISK]")
    print(f"  Split date: {split_date}  (IN < split ≤ OOS)")
    print("=" * 65)

    # Load models
    predictor = Predictor()
    predictor.load()
    strategy_predictor = StrategyPredictor()
    strategy_predictor.load()
    regime_detector = RegimeDetector()

    try:
        news_engine = NewsSentimentEngine()
    except Exception:
        news_engine = None

    try:
        oc_engine = OptionChainFeatureEngine()
    except Exception:
        oc_engine = None

    vol_model = VolSurfaceModel(max_strike_offset=_PROFILE.max_strike_offset) if _PROFILE.use_vol_surface else None

    rl_agent = RLExitAgent()
    if not rl_agent.load():
        rl_agent = None

    print(f"  ML model:   {'loaded' if predictor.is_loaded else 'MISSING'}")
    print(f"  RL agent:   {'loaded' if rl_agent else 'disabled'}")
    print(f"  Vol surface:{'enabled' if vol_model else 'disabled'}")

    all_days = get_available_days()
    is_days = [d for d in all_days if d < split_date]
    oos_days = [d for d in all_days if d >= split_date]

    print(
        f"\n  IN-SAMPLE days:     {len(is_days)}  ({is_days[0] if is_days else '-'} → {is_days[-1] if is_days else '-'})"
    )
    print(
        f"  OUT-OF-SAMPLE days: {len(oos_days)}  ({oos_days[0] if oos_days else '-'} → {oos_days[-1] if oos_days else '-'})"
    )

    # Warmup candles
    warmup = read_sql(
        "SELECT timestamp, symbol, open, high, low, close, volume, vwap, oi "
        "FROM minute_candles WHERE symbol = 'NIFTY-I' "
        "AND timestamp < :dt ORDER BY timestamp DESC LIMIT 300",
        {"dt": str(all_days[0])},
    )
    if not warmup.empty:
        warmup["timestamp"] = pd.to_datetime(warmup["timestamp"])
        warmup = warmup.sort_values("timestamp").reset_index(drop=True)

    def run_period(days, label):
        trades = []
        wm = warmup.copy()
        print(f"\n  ── {label} ({'×'.join(str(d) for d in days[:2])}{'...' if len(days) > 2 else ''}) ──")
        for d in days:
            day_trades = replay_day(
                replay_date=d,
                predictor=predictor,
                strategy_predictor=strategy_predictor,
                regime_detector=regime_detector,
                warmup_candles=wm,
                news_engine=news_engine,
                oc_engine=oc_engine,
                vol_model=vol_model,
                rl_agent=rl_agent,
                verbose=not args.quiet,
            )
            trades.extend(day_trades)
            # Carry warmup forward
            day_candles = read_sql(
                "SELECT timestamp, symbol, open, high, low, close, volume, vwap, oi "
                "FROM minute_candles WHERE symbol = 'NIFTY-I' AND timestamp::date = :dt ORDER BY timestamp",
                {"dt": str(d)},
            )
            if not day_candles.empty:
                day_candles["timestamp"] = pd.to_datetime(day_candles["timestamp"])
                wm = pd.concat([wm, day_candles], ignore_index=True).tail(500)
            if oc_engine:
                oc_engine.clear_cache()
        return trades

    is_trades = run_period(is_days, "IN-SAMPLE")
    oos_trades = run_period(oos_days, "OUT-OF-SAMPLE")

    is_m = compute_metrics(is_trades, "IN-SAMPLE")
    oos_m = compute_metrics(oos_trades, "OUT-OF-SAMPLE")

    print_comparison(is_m, oos_m)

    # Save combined CSV
    all_trades = is_trades + oos_trades
    if all_trades:
        df = pd.DataFrame(all_trades)
        df["period"] = df["entry_time"].apply(lambda t: "OOS" if pd.to_datetime(str(t)).date() >= split_date else "IS")
        out = f"backtest_results/forward_test_{args.risk}_{args.split}.csv"
        df.to_csv(out, index=False)
        print(f"  Results saved → {out}")


if __name__ == "__main__":
    main()
