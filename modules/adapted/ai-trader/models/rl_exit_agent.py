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
Reinforcement Learning Exit Policy
───────────────────────────────────
Learns optimal exit timing using Q-learning on historical option premium
trajectories. Replaces fixed SL/TGT/timeout with a learned policy that
adapts to market conditions.

State space (8 features):
  - unrealized_pnl_pct:  current P&L as % of entry premium
  - bars_held:           minutes since entry (normalized)
  - premium_momentum:    rate of change of premium (last 3 bars)
  - premium_volatility:  std of premium changes (last 5 bars)
  - distance_to_sl:      how far from current SL (as %)
  - distance_to_tgt:     how far from target (as %)
  - trailing_active:     1 if trailing stop is active, else 0
  - peak_gain_pct:       max unrealized gain since entry (as %)

Action space (3 actions):
  0 = HOLD     — keep position open
  1 = EXIT     — close position now
  2 = TIGHTEN  — tighten SL to lock in more profit

Reward:
  - On EXIT: realized P&L as fraction of entry premium
  - On HOLD at terminal: realized P&L (timeout/SL/TGT hit)
  - Small negative reward per bar held (opportunity cost)

Usage:
  from models.rl_exit_agent import RLExitAgent
  agent = RLExitAgent()
  agent.load()
  action = agent.decide(state_dict)  # returns "HOLD", "EXIT", or "TIGHTEN"
"""

import json
import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from utils.logger import get_logger

logger = get_logger("rl_exit_agent")

MODEL_DIR = Path("models/saved")
RL_MODEL_PATH = MODEL_DIR / "rl_exit_agent.pkl"

# State feature names and normalization ranges
STATE_FEATURES = [
    "unrealized_pnl_pct",
    "bars_held_norm",
    "premium_momentum",
    "premium_volatility",
    "distance_to_sl",
    "distance_to_tgt",
    "trailing_active",
    "peak_gain_pct",
]

ACTIONS = ["HOLD", "EXIT", "TIGHTEN"]
N_ACTIONS = len(ACTIONS)
N_FEATURES = len(STATE_FEATURES)

# Discretization bins for each feature (for tabular Q-learning)
BINS = {
    "unrealized_pnl_pct": [-0.30, -0.15, -0.05, 0.0, 0.05, 0.15, 0.30, 0.50],
    "bars_held_norm": [0.1, 0.2, 0.3, 0.5, 0.7, 0.85, 1.0],
    "premium_momentum": [-0.05, -0.02, -0.005, 0.0, 0.005, 0.02, 0.05],
    "premium_volatility": [0.005, 0.01, 0.02, 0.03, 0.05, 0.08],
    "distance_to_sl": [0.0, 0.05, 0.10, 0.20, 0.35, 0.50],
    "distance_to_tgt": [0.0, 0.10, 0.25, 0.40, 0.60, 0.80],
    "trailing_active": [0.5],  # binary: 0 or 1
    "peak_gain_pct": [0.0, 0.05, 0.10, 0.20, 0.35, 0.50],
}


def discretize_state(state: dict[str, float]) -> tuple[int, ...]:
    """Convert continuous state to discrete bin indices for Q-table lookup."""
    indices = []
    for feat in STATE_FEATURES:
        val = state.get(feat, 0.0)
        bins = BINS[feat]
        idx = int(np.digitize(val, bins))
        indices.append(idx)
    return tuple(indices)


def compute_state(
    entry_premium: float,
    current_premium: float,
    bars_held: int,
    max_hold_bars: int,
    sl: float,
    target: float,
    trailing_active: bool,
    peak_premium: float,
    premium_history: list[float],
) -> dict[str, float]:
    """Compute the RL state features from trade context."""
    if entry_premium <= 0:
        return dict.fromkeys(STATE_FEATURES, 0.0)

    unrealized_pnl_pct = (current_premium - entry_premium) / entry_premium
    bars_held_norm = bars_held / max(max_hold_bars, 1)
    peak_gain_pct = (peak_premium - entry_premium) / entry_premium

    # Premium momentum (rate of change over last 3 bars)
    if len(premium_history) >= 3:
        recent = premium_history[-3:]
        momentum = (recent[-1] - recent[0]) / entry_premium
    else:
        momentum = 0.0

    # Premium volatility (std of changes over last 5 bars)
    if len(premium_history) >= 5:
        changes = np.diff(premium_history[-5:]) / entry_premium
        vol = float(np.std(changes))
    elif len(premium_history) >= 2:
        changes = np.diff(premium_history) / entry_premium
        vol = float(np.std(changes))
    else:
        vol = 0.0

    # Distance to SL and target
    dist_sl = (current_premium - sl) / entry_premium if sl > 0 else 1.0
    dist_tgt = (target - current_premium) / entry_premium if target > 0 else 1.0

    return {
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "bars_held_norm": bars_held_norm,
        "premium_momentum": momentum,
        "premium_volatility": vol,
        "distance_to_sl": max(dist_sl, 0),
        "distance_to_tgt": max(dist_tgt, 0),
        "trailing_active": 1.0 if trailing_active else 0.0,
        "peak_gain_pct": max(peak_gain_pct, 0),
    }


class RLExitAgent:
    """Tabular Q-learning agent for exit decisions."""

    def __init__(
        self,
        learning_rate: float = 0.1,
        discount_factor: float = 0.95,
        epsilon: float = 0.1,
        hold_penalty: float = -0.001,
    ):
        self.lr = learning_rate
        self.gamma = discount_factor
        self.epsilon = epsilon
        self.hold_penalty = hold_penalty

        # Q-table: state_tuple -> [q_hold, q_exit, q_tighten]
        self.q_table: dict[tuple, np.ndarray] = {}
        self.is_loaded = False
        self.training_episodes = 0

    def _get_q(self, state_key: tuple) -> np.ndarray:
        """Get Q-values for a state, initializing if unseen."""
        if state_key not in self.q_table:
            # Initialize with slight bias towards HOLD (conservative)
            self.q_table[state_key] = np.array([0.01, 0.0, 0.0])
        return self.q_table[state_key]

    def decide(self, state: dict[str, float], explore: bool = False) -> str:
        """
        Choose an action given the current state.

        Args:
            state: Dict of state features
            explore: If True, use epsilon-greedy (for training)

        Returns: "HOLD", "EXIT", or "TIGHTEN"
        """
        state_key = discretize_state(state)
        q_vals = self._get_q(state_key)

        if explore and np.random.random() < self.epsilon:
            action_idx = np.random.randint(N_ACTIONS)
        else:
            action_idx = int(np.argmax(q_vals))

        return ACTIONS[action_idx]

    def update(
        self,
        state: dict[str, float],
        action: str,
        reward: float,
        next_state: dict[str, float] | None = None,
        done: bool = False,
    ):
        """Q-learning update step."""
        state_key = discretize_state(state)
        action_idx = ACTIONS.index(action)
        q_vals = self._get_q(state_key)

        if done or next_state is None:
            target = reward
        else:
            next_key = discretize_state(next_state)
            next_q = self._get_q(next_key)
            target = reward + self.gamma * np.max(next_q)

        q_vals[action_idx] += self.lr * (target - q_vals[action_idx])
        self.q_table[state_key] = q_vals

    def train_on_trajectory(
        self,
        premium_trajectory: list[float],
        entry_premium: float,
        sl: float,
        target: float,
        max_hold_bars: int,
        lot_size: int = 65,
        commission: float = 40.0,
    ) -> dict:
        """
        Train on a single trade's premium trajectory.

        The trajectory is a list of close premiums for each bar.
        The agent learns by replaying the trajectory and choosing actions.

        Returns: episode stats dict
        """
        if len(premium_trajectory) < 3 or entry_premium <= 0:
            return {"reward": 0, "bars": 0, "action": "SKIP"}

        peak_premium = entry_premium
        trailing_active = False
        trailing_sl = sl
        history = [entry_premium]
        total_reward = 0.0
        exit_bar = len(premium_trajectory) - 1
        exit_action = "TIMEOUT"

        for bar_idx, current_prem in enumerate(premium_trajectory):
            history.append(current_prem)
            peak_premium = max(peak_premium, current_prem)

            # Check trailing activation
            gain_pct = (peak_premium - entry_premium) / entry_premium
            if gain_pct >= 0.15 and not trailing_active:
                trailing_active = True
                trailing_sl = entry_premium

            # Current effective SL
            effective_sl = max(sl, trailing_sl) if trailing_active else sl

            state = compute_state(
                entry_premium=entry_premium,
                current_premium=current_prem,
                bars_held=bar_idx,
                max_hold_bars=max_hold_bars,
                sl=effective_sl,
                target=target,
                trailing_active=trailing_active,
                peak_premium=peak_premium,
                premium_history=history,
            )

            # Check if trade would have been forced out
            forced_exit = False
            if current_prem <= effective_sl:
                forced_exit = True
                exit_action = "SL"
            elif current_prem >= target:
                forced_exit = True
                exit_action = "TARGET"
            elif bar_idx >= max_hold_bars - 1:
                forced_exit = True
                exit_action = "TIMEOUT"

            if forced_exit:
                # Terminal state — compute final reward
                pnl_pct = (current_prem - entry_premium) / entry_premium
                self.update(state, "EXIT", pnl_pct, done=True)
                total_reward += pnl_pct
                exit_bar = bar_idx
                break

            # Agent decides
            action = self.decide(state, explore=True)

            if action == "EXIT":
                pnl_pct = (current_prem - entry_premium) / entry_premium
                self.update(state, action, pnl_pct, done=True)
                total_reward += pnl_pct
                exit_bar = bar_idx
                exit_action = "RL_EXIT"
                break

            if action == "TIGHTEN":
                # Tighten SL: move up to 50% of current gain
                if current_prem > entry_premium:
                    new_sl = entry_premium + 0.5 * (current_prem - entry_premium)
                    effective_sl = max(effective_sl, new_sl)
                    if not trailing_active:
                        trailing_active = True
                    trailing_sl = effective_sl

                # Small positive reward for good tightening
                tighten_reward = 0.002 if current_prem > entry_premium else -0.002
                next_state = compute_state(
                    entry_premium,
                    current_prem,
                    bar_idx + 1,
                    max_hold_bars,
                    effective_sl,
                    target,
                    trailing_active,
                    peak_premium,
                    history,
                )
                self.update(state, action, tighten_reward, next_state)
                total_reward += tighten_reward

            else:  # HOLD
                hold_reward = self.hold_penalty
                if bar_idx < len(premium_trajectory) - 1:
                    next_prem = premium_trajectory[bar_idx + 1]
                    next_state = compute_state(
                        entry_premium,
                        next_prem,
                        bar_idx + 1,
                        max_hold_bars,
                        effective_sl,
                        target,
                        trailing_active,
                        peak_premium,
                        history,
                    )
                    self.update(state, action, hold_reward, next_state)
                total_reward += hold_reward

        self.training_episodes += 1
        return {
            "reward": round(total_reward, 4),
            "bars": exit_bar,
            "action": exit_action,
            "states_seen": len(self.q_table),
        }

    def save(self, path: str | None = None):
        """Save Q-table to disk."""
        path = path or str(RL_MODEL_PATH)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "q_table": self.q_table,
            "training_episodes": self.training_episodes,
            "lr": self.lr,
            "gamma": self.gamma,
            "epsilon": self.epsilon,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        logger.info(f"Saved RL exit agent: {len(self.q_table)} states, {self.training_episodes} episodes -> {path}")

    def load(self, path: str | None = None) -> bool:
        """Load Q-table from disk."""
        path = path or str(RL_MODEL_PATH)
        if not os.path.exists(path):
            logger.warning(f"No RL model found at {path}")
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.q_table = data["q_table"]
            self.training_episodes = data.get("training_episodes", 0)
            self.is_loaded = True
            logger.info(f"Loaded RL exit agent: {len(self.q_table)} states, {self.training_episodes} episodes")
            return True
        except Exception as e:
            logger.exception(f"Failed to load RL model: {e}")
            return False

    def policy_summary(self) -> dict:
        """Summarize learned policy statistics."""
        if not self.q_table:
            return {"states": 0, "episodes": 0}

        actions_chosen = {"HOLD": 0, "EXIT": 0, "TIGHTEN": 0}
        for q_vals in self.q_table.values():
            best = ACTIONS[int(np.argmax(q_vals))]
            actions_chosen[best] += 1

        return {
            "states": len(self.q_table),
            "episodes": self.training_episodes,
            "policy_distribution": actions_chosen,
            "avg_q_hold": np.mean([q[0] for q in self.q_table.values()]),
            "avg_q_exit": np.mean([q[1] for q in self.q_table.values()]),
            "avg_q_tighten": np.mean([q[2] for q in self.q_table.values()]),
        }
