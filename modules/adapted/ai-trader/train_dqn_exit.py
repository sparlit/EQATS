#!/usr/bin/env python3
"""
Train DQN Exit Agent
─────────────────────
Trains the Deep Q-Network exit agent on historical option premium
trajectories. Same data pipeline as train_rl_exit.py but uses the
neural network agent for better generalization.

Usage:
  python scripts/train_dqn_exit.py                 # 10 epochs
  python scripts/train_dqn_exit.py --epochs 20
  python scripts/train_dqn_exit.py --evaluate
"""

import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import numpy as np
from models.dqn_exit_agent import DQNExitAgent
from models.rl_exit_agent import compute_state
from scripts.train_rl_exit import extract_premium_trajectories
from backtest.option_resolver import clear_cache
from database.db import read_sql
from utils.logger import get_logger

logger = get_logger("train_dqn_exit")


def train(epochs: int = 10, max_hold: int = 45):
    agent = DQNExitAgent(
        lr=1e-3,
        gamma=0.95,
        epsilon=0.20,
        epsilon_min=0.02,
        epsilon_decay=0.998,
        batch_size=64,
        target_update_freq=200,
        hold_penalty=-0.001,
    )

    if agent.load():
        print(f"  Resuming: {agent.episodes} episodes, ε={agent.epsilon:.4f}")
    else:
        print("  Training from scratch")

    days = read_sql("""
        SELECT DISTINCT timestamp::date AS day
        FROM minute_candles WHERE symbol = 'NIFTY-I' ORDER BY 1
    """)
    trading_days = list(days["day"])
    print(f"  Trading days: {len(trading_days)}")
    print(f"  Network params: {agent.policy_summary()['params']:,}")

    best_reward = -float("inf")

    for epoch in range(epochs):
        epoch_reward = 0.0
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

        avg_reward = epoch_reward / max(epoch_episodes, 1)
        print(
            f"  Epoch {epoch+1}/{epochs}  |  "
            f"Episodes: {epoch_episodes}  |  "
            f"Avg reward: {avg_reward:+.4f}  |  "
            f"Buffer: {agent.policy_summary()['buffer_size']:,}  |  "
            f"ε: {agent.epsilon:.4f}  |  "
            f"Steps: {agent.training_steps:,}"
        )

        if avg_reward > best_reward:
            best_reward = avg_reward
            agent.save()

    agent.save()
    s = agent.policy_summary()
    print(f"\n  DQN training complete!")
    print(f"  Total episodes:  {s['episodes']}")
    print(f"  Training steps:  {s['training_steps']}")
    print(f"  Final ε:         {s['epsilon']}")
    return agent


def evaluate(max_hold: int = 45):
    agent = DQNExitAgent()
    if not agent.load():
        print("  No DQN model found. Run training first.")
        return

    print(f"  Loaded DQN: {agent.episodes} episodes, ε={agent.epsilon:.4f}")

    days = read_sql("""
        SELECT DISTINCT timestamp::date AS day
        FROM minute_candles WHERE symbol = 'NIFTY-I' ORDER BY 1
    """)
    trading_days = list(days["day"])

    pnls = []
    exit_reasons = {}

    for day in trading_days:
        clear_cache()
        trajectories = extract_premium_trajectories(day, max_hold=max_hold)
        for traj in trajectories:
            entry  = traj["entry_premium"]
            sl     = traj["sl"]
            target = traj["target"]
            peak   = entry
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

                if prem <= eff_sl:
                    exit_prem = eff_sl; exit_reason = "SL"; break
                if prem >= target:
                    exit_prem = target; exit_reason = "TARGET"; break

                state = compute_state(entry, prem, bar_idx, max_hold,
                                      eff_sl, target, trailing_active, peak, history)
                action = agent.decide(state, explore=False)

                if action == "EXIT":
                    exit_prem = prem; exit_reason = "DQN_EXIT"; break
                elif action == "TIGHTEN":
                    if prem > entry:
                        new_sl = entry + 0.5 * (prem - entry)
                        trailing_sl = max(trailing_sl, new_sl)
                        trailing_active = True
            else:
                exit_prem = traj["trajectory"][-1]
                exit_reason = "TIMEOUT"

            pnl_pct = (exit_prem - entry) / entry
            pnls.append(pnl_pct)
            exit_reasons[exit_reason] = exit_reasons.get(exit_reason, 0) + 1

    pnls = np.array(pnls)
    print(f"\n  DQN Evaluation Results ({len(pnls)} trajectories):")
    print(f"  Avg P&L%:  {pnls.mean()*100:+.2f}%")
    print(f"  Win rate:  {(pnls > 0).mean()*100:.1f}%")
    print(f"  Median:    {np.median(pnls)*100:+.2f}%")
    print(f"  Std:       {pnls.std()*100:.2f}%")
    print(f"  Best:      {pnls.max()*100:+.2f}%")
    print(f"  Worst:     {pnls.min()*100:+.2f}%")
    print(f"  Exit reasons: {exit_reasons}")


def main():
    parser = argparse.ArgumentParser(description="Train DQN exit agent")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--max-hold", type=int, default=45)
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  DQN EXIT AGENT TRAINING")
    print("=" * 60)

    if args.evaluate:
        evaluate(args.max_hold)
    else:
        train(args.epochs, args.max_hold)


if __name__ == "__main__":
    main()
