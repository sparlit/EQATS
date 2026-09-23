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
Train RL Exit Agent
───────────────────
Trains the Q-learning exit agent on historical option premium trajectories
extracted from our tick/candle database.

For each historical trade opportunity:
  1. Resolve the option contract at a signal point
  2. Extract the full premium trajectory (entry → +N bars)
  3. Train the RL agent on this trajectory

The agent learns when to HOLD, EXIT, or TIGHTEN across many episodes.

Usage:
  python scripts/train_rl_exit.py                # train on all available data
  python scripts/train_rl_exit.py --epochs 20    # more training passes
  python scripts/train_rl_exit.py --evaluate     # evaluate without training
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

import numpy as np
import pandas as pd
from backtest.option_resolver import (
    build_option_symbol,
    clear_cache,
    get_atm_strike,
    get_nearest_expiry,
    load_option_premiums_for_day,
)
from models.rl_exit_agent import RLExitAgent
from utils.logger import get_logger

from database.db import read_sql

logger = get_logger("train_rl_exit")


def extract_premium_trajectories(trading_date: date, max_hold: int = 45) -> list:
    """
    Extract option premium trajectories for training.

    For each minute of the trading day, if there's a valid option contract,
    extract the premium series for the next `max_hold` bars.

    Returns list of dicts: {entry_premium, trajectory, sl, target, direction}
    """
    # Load NIFTY candles for the day
    candles = read_sql(
        "SELECT timestamp, close FROM minute_candles "
        "WHERE symbol = 'NIFTY-I' AND timestamp::date = :dt "
        "ORDER BY timestamp",
        {"dt": str(trading_date)},
    )
    if candles.empty or len(candles) < 60:
        return []

    candles["timestamp"] = pd.to_datetime(candles["timestamp"])
    expiry = get_nearest_expiry(trading_date)
    if expiry is None:
        return []

    trajectories = []

    # Sample every 5th minute to avoid massive overlap
    sample_indices = range(30, len(candles) - max_hold, 5)

    for idx in sample_indices:
        row = candles.iloc[idx]
        spot = float(row["close"])
        ts = row["timestamp"]
        atm = get_atm_strike(spot)

        for direction in ["CALL", "PUT"]:
            opt_type = "CE" if direction == "CALL" else "PE"

            # Try ATM and nearby strikes
            for offset in [0, 1, -1]:
                strike = atm + offset * 50
                sym = build_option_symbol(expiry, strike, opt_type)
                pdf = load_option_premiums_for_day(sym, trading_date)
                if pdf.empty:
                    continue

                # Find entry point
                mask = (pdf["timestamp"] - ts).abs() <= pd.Timedelta(minutes=1)
                entry_rows = pdf[mask]
                if entry_rows.empty:
                    continue

                entry_prem = float(entry_rows.iloc[0]["premium"])
                if entry_prem <= 0 or entry_prem > 300:
                    continue

                # Extract trajectory: premiums for next max_hold bars
                entry_ts = entry_rows.iloc[0]["timestamp"]
                future = pdf[pdf["timestamp"] > entry_ts].head(max_hold)
                if len(future) < 5:
                    continue

                trajectory = future["premium"].tolist()
                sl = entry_prem * 0.70  # 30% SL
                target = entry_prem * 1.50  # 50% TGT

                trajectories.append(
                    {
                        "entry_premium": entry_prem,
                        "trajectory": trajectory,
                        "sl": sl,
                        "target": target,
                        "direction": direction,
                        "symbol": sym,
                        "timestamp": str(ts),
                    }
                )
                break  # one strike per direction per time

    return trajectories


def train_agent(epochs: int = 10, max_hold: int = 45):
    """Train the RL exit agent on all available historical data."""
    agent = RLExitAgent(
        learning_rate=0.1,
        discount_factor=0.95,
        epsilon=0.15,
        hold_penalty=-0.001,
    )

    # Try loading existing model for incremental training
    if agent.load():
        print(f"  Loaded existing model: {len(agent.q_table)} states")
        agent.epsilon = 0.10  # less exploration for fine-tuning
    else:
        print("  Training from scratch")

    # Get all available trading days
    days = read_sql("""
        SELECT DISTINCT timestamp::date as day
        FROM minute_candles WHERE symbol = 'NIFTY-I'
        ORDER BY 1
    """)
    trading_days = list(days["day"])
    print(f"  Available days: {len(trading_days)}")

    total_episodes = 0
    total_reward = 0
    best_reward = -float("inf")

    for epoch in range(epochs):
        epoch_reward = 0
        epoch_episodes = 0

        for day in trading_days:
            clear_cache()
            trajectories = extract_premium_trajectories(day, max_hold=max_hold)

            for traj in trajectories:
                result = agent.train_on_trajectory(
                    premium_trajectory=traj["trajectory"],
                    entry_premium=traj["entry_premium"],
                    sl=traj["sl"],
                    target=traj["target"],
                    max_hold_bars=max_hold,
                )
                epoch_reward += result["reward"]
                epoch_episodes += 1

        total_episodes += epoch_episodes
        total_reward += epoch_reward
        avg_reward = epoch_reward / max(epoch_episodes, 1)

        # Decay exploration
        agent.epsilon = max(0.02, agent.epsilon * 0.9)

        print(
            f"  Epoch {epoch + 1}/{epochs}  |  "
            f"Episodes: {epoch_episodes}  |  "
            f"Avg reward: {avg_reward:+.4f}  |  "
            f"States: {len(agent.q_table)}  |  "
            f"ε: {agent.epsilon:.3f}"
        )

        if avg_reward > best_reward:
            best_reward = avg_reward
            agent.save()

    # Final save
    agent.save()

    # Print policy summary
    summary = agent.policy_summary()
    print("\n  Training complete!")
    print(f"  Total episodes:  {total_episodes}")
    print(f"  Q-table states:  {summary['states']}")
    print(f"  Policy distribution: {summary['policy_distribution']}")
    print(f"  Avg Q(HOLD):   {summary['avg_q_hold']:+.4f}")
    print(f"  Avg Q(EXIT):   {summary['avg_q_exit']:+.4f}")
    print(f"  Avg Q(TIGHTEN):{summary['avg_q_tighten']:+.4f}")

    return agent


def evaluate_agent(max_hold: int = 45):
    """Evaluate the trained agent without updating it."""
    agent = RLExitAgent()
    if not agent.load():
        print("  No trained model found. Run training first.")
        return

    print(f"  Loaded model: {len(agent.q_table)} states, {agent.training_episodes} episodes")

    days = read_sql("""
        SELECT DISTINCT timestamp::date as day
        FROM minute_candles WHERE symbol = 'NIFTY-I'
        ORDER BY 1
    """)
    trading_days = list(days["day"])

    results = {"RL_EXIT": 0, "TARGET": 0, "SL": 0, "TIMEOUT": 0, "TIGHTEN_EXIT": 0}
    pnls = []

    for day in trading_days:
        clear_cache()
        trajectories = extract_premium_trajectories(day, max_hold=max_hold)

        for traj in trajectories:
            entry = traj["entry_premium"]
            sl = traj["sl"]
            target = traj["target"]
            peak = entry
            trailing_active = False
            trailing_sl = sl
            history = [entry]

            exit_prem = entry
            exit_reason = "TIMEOUT"

            for bar_idx, prem in enumerate(traj["trajectory"]):
                history.append(prem)
                peak = max(peak, prem)

                if (peak - entry) / entry >= 0.15 and not trailing_active:
                    trailing_active = True
                    trailing_sl = entry

                eff_sl = max(sl, trailing_sl) if trailing_active else sl

                # Check forced exits
                if prem <= eff_sl:
                    exit_prem = eff_sl
                    exit_reason = "SL"
                    break
                if prem >= target:
                    exit_prem = target
                    exit_reason = "TARGET"
                    break

                from models.rl_exit_agent import compute_state

                state = compute_state(
                    entry,
                    prem,
                    bar_idx,
                    max_hold,
                    eff_sl,
                    target,
                    trailing_active,
                    peak,
                    history,
                )

                action = agent.decide(state, explore=False)
                if action == "EXIT":
                    exit_prem = prem
                    exit_reason = "RL_EXIT"
                    break
                if action == "TIGHTEN":
                    if prem > entry:
                        new_sl = entry + 0.5 * (prem - entry)
                        trailing_sl = max(trailing_sl, new_sl)
                        trailing_active = True

            else:
                exit_prem = traj["trajectory"][-1]
                exit_reason = "TIMEOUT"

            pnl_pct = (exit_prem - entry) / entry
            pnls.append(pnl_pct)
            results[exit_reason] = results.get(exit_reason, 0) + 1

    pnls = np.array(pnls)
    print("\n  Evaluation Results:")
    print(f"  Total trajectories: {len(pnls)}")
    print(f"  Avg P&L%:  {pnls.mean() * 100:+.2f}%")
    print(f"  Win rate:  {(pnls > 0).mean() * 100:.1f}%")
    print(f"  Median:    {np.median(pnls) * 100:+.2f}%")
    print(f"  Std:       {pnls.std() * 100:.2f}%")
    print(f"  Best:      {pnls.max() * 100:+.2f}%")
    print(f"  Worst:     {pnls.min() * 100:+.2f}%")
    print(f"\n  Exit reasons: {results}")


def main():
    parser = argparse.ArgumentParser(description="Train RL exit agent")
    parser.add_argument("--epochs", type=int, default=10, help="Training epochs")
    parser.add_argument("--max-hold", type=int, default=45, help="Max bars per trajectory")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate only")
    args = parser.parse_args()

    print("=" * 60)
    print("  RL EXIT AGENT TRAINING")
    print("=" * 60)

    if args.evaluate:
        evaluate_agent(args.max_hold)
    else:
        train_agent(args.epochs, args.max_hold)


if __name__ == "__main__":
    main()
