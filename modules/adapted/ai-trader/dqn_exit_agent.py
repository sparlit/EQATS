"""
Deep Q-Network (DQN) Exit Agent
─────────────────────────────────
Replaces the tabular Q-agent with a small neural network that can
generalize to unseen continuous state combinations.

Architecture:
  Input:  8 state features (continuous)
  Hidden: 64 → 64 → 32 (ReLU, LayerNorm for stability)
  Output: 3 Q-values (HOLD, EXIT, TIGHTEN)

Training:
  - Experience Replay: circular buffer of (s, a, r, s', done)
  - Target network: hard-update every N steps
  - Epsilon-greedy exploration with decay
  - Huber loss for robustness to outliers

Usage:
  from models.dqn_exit_agent import DQNExitAgent
  agent = DQNExitAgent()
  agent.load()  # loads from models/saved/dqn_exit_agent.pt
  action = agent.decide(state_dict)  # "HOLD", "EXIT", "TIGHTEN"
"""

import os
import random
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from utils.logger import get_logger

logger = get_logger("dqn_exit_agent")

MODEL_DIR  = Path("models/saved")
DQN_PATH   = MODEL_DIR / "dqn_exit_agent.pt"

# ── State / Action ────────────────────────────────────────────────────────────
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
ACTIONS   = ["HOLD", "EXIT", "TIGHTEN"]
N_STATES  = len(STATE_FEATURES)
N_ACTIONS = len(ACTIONS)

# ── Normalisation stats (approx from training data) ──────────────────────────
_STATE_MEAN = np.array([0.02, 0.45, 0.0, 0.02, 0.15, 0.35, 0.25, 0.06], dtype=np.float32)
_STATE_STD  = np.array([0.15, 0.30, 0.02, 0.02, 0.15, 0.25, 0.43, 0.10], dtype=np.float32)


def state_dict_to_tensor(state: Dict[str, float]) -> torch.Tensor:
    arr = np.array([state.get(f, 0.0) for f in STATE_FEATURES], dtype=np.float32)
    arr = (arr - _STATE_MEAN) / (_STATE_STD + 1e-8)
    return torch.from_numpy(arr).unsqueeze(0)  # (1, 8)


# ── Neural Network ────────────────────────────────────────────────────────────
class QNetwork(nn.Module):
    def __init__(self, n_states: int = N_STATES, n_actions: int = N_ACTIONS):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_states, 64),
            nn.LayerNorm(64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.LayerNorm(64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, n_actions),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ── Experience Replay Buffer ──────────────────────────────────────────────────
class ReplayBuffer:
    def __init__(self, capacity: int = 50_000):
        self.buf = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buf.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        batch = random.sample(self.buf, batch_size)
        s, a, r, ns, d = zip(*batch)
        return (
            torch.stack(s).squeeze(1),
            torch.tensor(a, dtype=torch.long),
            torch.tensor(r, dtype=torch.float32),
            torch.stack(ns).squeeze(1),
            torch.tensor(d, dtype=torch.float32),
        )

    def __len__(self):
        return len(self.buf)


# ── DQN Agent ─────────────────────────────────────────────────────────────────
class DQNExitAgent:
    """
    DQN-based exit policy agent.

    Keeps a separate target network that is hard-copied from the online
    network every `target_update_freq` gradient steps for training stability.
    """

    def __init__(
        self,
        lr: float = 1e-3,
        gamma: float = 0.95,
        epsilon: float = 0.15,
        epsilon_min: float = 0.02,
        epsilon_decay: float = 0.995,
        batch_size: int = 64,
        target_update_freq: int = 200,
        buffer_capacity: int = 50_000,
        hold_penalty: float = -0.001,
    ):
        self.lr               = lr
        self.gamma            = gamma
        self.epsilon          = epsilon
        self.epsilon_min      = epsilon_min
        self.epsilon_decay    = epsilon_decay
        self.batch_size       = batch_size
        self.target_update_freq = target_update_freq
        self.hold_penalty     = hold_penalty

        self.device = torch.device("cpu")

        self.online_net = QNetwork().to(self.device)
        self.target_net = QNetwork().to(self.device)
        self.target_net.load_state_dict(self.online_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.online_net.parameters(), lr=lr)
        self.buffer    = ReplayBuffer(buffer_capacity)

        self.steps          = 0
        self.training_steps = 0
        self.episodes       = 0
        self.is_loaded      = False

    # ── Inference ─────────────────────────────────────────────────────────────
    def decide(self, state: Dict[str, float], explore: bool = False) -> str:
        if explore and random.random() < self.epsilon:
            return random.choice(ACTIONS)

        self.online_net.eval()
        with torch.no_grad():
            t = state_dict_to_tensor(state).to(self.device)
            q_vals = self.online_net(t)
            action_idx = int(q_vals.argmax(dim=1).item())
        return ACTIONS[action_idx]

    def q_values(self, state: Dict[str, float]) -> Dict[str, float]:
        """Return raw Q-values for all actions (useful for debugging)."""
        self.online_net.eval()
        with torch.no_grad():
            t = state_dict_to_tensor(state).to(self.device)
            q_vals = self.online_net(t).squeeze(0).tolist()
        return {ACTIONS[i]: round(q_vals[i], 4) for i in range(N_ACTIONS)}

    # ── Training ──────────────────────────────────────────────────────────────
    def push(self, state, action: str, reward: float, next_state, done: bool):
        s_t  = state_dict_to_tensor(state)
        ns_t = state_dict_to_tensor(next_state) if next_state else s_t
        a_idx = ACTIONS.index(action)
        self.buffer.push(s_t, a_idx, reward, ns_t, done)
        self.steps += 1

    def learn(self) -> Optional[float]:
        """One gradient step. Returns loss or None if buffer too small."""
        if len(self.buffer) < self.batch_size:
            return None

        self.online_net.train()
        s, a, r, ns, d = self.buffer.sample(self.batch_size)
        s  = s.to(self.device)
        ns = ns.to(self.device)
        a  = a.to(self.device)
        r  = r.to(self.device)
        d  = d.to(self.device)

        # Current Q
        q_curr = self.online_net(s).gather(1, a.unsqueeze(1)).squeeze(1)

        # Target Q (Double DQN: online selects action, target evaluates)
        with torch.no_grad():
            online_actions = self.online_net(ns).argmax(dim=1, keepdim=True)
            q_next = self.target_net(ns).gather(1, online_actions).squeeze(1)
            q_target = r + self.gamma * q_next * (1 - d)

        loss = F.huber_loss(q_curr, q_target)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online_net.parameters(), 1.0)
        self.optimizer.step()

        self.training_steps += 1
        if self.training_steps % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.online_net.state_dict())

        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        return float(loss.item())

    def train_on_trajectory(
        self,
        premium_trajectory: List[float],
        entry_premium: float,
        sl: float,
        target: float,
        max_hold_bars: int,
    ) -> Dict:
        """
        Train on a single trade trajectory (same interface as tabular agent).
        Pushes transitions to replay buffer and runs gradient steps.
        """
        from models.rl_exit_agent import compute_state  # reuse state computation

        if len(premium_trajectory) < 3 or entry_premium <= 0:
            return {"reward": 0, "bars": 0, "action": "SKIP"}

        peak_premium    = entry_premium
        trailing_active = False
        trailing_sl     = sl
        history         = [entry_premium]
        total_reward    = 0.0
        exit_bar        = len(premium_trajectory) - 1
        exit_action     = "TIMEOUT"

        for bar_idx, current_prem in enumerate(premium_trajectory):
            history.append(current_prem)
            peak_premium = max(peak_premium, current_prem)

            gain_pct = (peak_premium - entry_premium) / entry_premium
            if gain_pct >= 0.15 and not trailing_active:
                trailing_active = True
                trailing_sl = entry_premium

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

            # Forced exits
            forced = False
            if current_prem <= effective_sl:
                forced = True; exit_action = "SL"
            elif current_prem >= target:
                forced = True; exit_action = "TARGET"
            elif bar_idx >= max_hold_bars - 1:
                forced = True; exit_action = "TIMEOUT"

            if forced:
                pnl_pct = (current_prem - entry_premium) / entry_premium
                total_reward += pnl_pct
                self.push(state, "EXIT", pnl_pct, None, True)
                self.learn()
                exit_bar = bar_idx
                break

            # Agent action
            action = self.decide(state, explore=True)

            if action == "EXIT":
                pnl_pct = (current_prem - entry_premium) / entry_premium
                total_reward += pnl_pct
                self.push(state, action, pnl_pct, None, True)
                self.learn()
                exit_bar = bar_idx
                exit_action = "DQN_EXIT"
                break

            elif action == "TIGHTEN":
                if current_prem > entry_premium:
                    new_sl = entry_premium + 0.5 * (current_prem - entry_premium)
                    effective_sl = max(effective_sl, new_sl)
                    trailing_active = True
                    trailing_sl = effective_sl
                reward = 0.002 if current_prem > entry_premium else -0.002
                if bar_idx < len(premium_trajectory) - 1:
                    next_prem = premium_trajectory[bar_idx + 1]
                    next_state = compute_state(
                        entry_premium, next_prem, bar_idx + 1,
                        max_hold_bars, effective_sl, target,
                        trailing_active, peak_premium, history,
                    )
                    self.push(state, action, reward, next_state, False)
                total_reward += reward

            else:  # HOLD
                reward = self.hold_penalty
                if bar_idx < len(premium_trajectory) - 1:
                    next_prem = premium_trajectory[bar_idx + 1]
                    next_state = compute_state(
                        entry_premium, next_prem, bar_idx + 1,
                        max_hold_bars, effective_sl, target,
                        trailing_active, peak_premium, history,
                    )
                    self.push(state, action, reward, next_state, False)
                total_reward += reward

            self.learn()

        self.episodes += 1
        return {
            "reward": round(total_reward, 4),
            "bars": exit_bar,
            "action": exit_action,
            "buffer_size": len(self.buffer),
            "epsilon": round(self.epsilon, 4),
        }

    # ── Persistence ───────────────────────────────────────────────────────────
    def save(self, path: str = None):
        path = path or str(DQN_PATH)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        torch.save({
            "online_state_dict":  self.online_net.state_dict(),
            "target_state_dict":  self.target_net.state_dict(),
            "optimizer_state":    self.optimizer.state_dict(),
            "epsilon":            self.epsilon,
            "episodes":           self.episodes,
            "training_steps":     self.training_steps,
        }, path)
        logger.info(f"DQN saved: {self.episodes} episodes, ε={self.epsilon:.4f} → {path}")

    def load(self, path: str = None) -> bool:
        path = path or str(DQN_PATH)
        if not os.path.exists(path):
            logger.warning(f"No DQN model at {path}")
            return False
        try:
            ckpt = torch.load(path, map_location=self.device, weights_only=True)
            self.online_net.load_state_dict(ckpt["online_state_dict"])
            self.target_net.load_state_dict(ckpt["target_state_dict"])
            self.optimizer.load_state_dict(ckpt["optimizer_state"])
            self.epsilon       = ckpt.get("epsilon", self.epsilon_min)
            self.episodes      = ckpt.get("episodes", 0)
            self.training_steps = ckpt.get("training_steps", 0)
            self.is_loaded = True
            logger.info(
                f"DQN loaded: {self.episodes} episodes, "
                f"ε={self.epsilon:.4f}, steps={self.training_steps}"
            )
            return True
        except Exception as e:
            logger.error(f"DQN load failed: {e}")
            return False

    def policy_summary(self) -> Dict:
        return {
            "type":           "DQN",
            "episodes":       self.episodes,
            "training_steps": self.training_steps,
            "epsilon":        round(self.epsilon, 4),
            "buffer_size":    len(self.buffer),
            "params":         sum(p.numel() for p in self.online_net.parameters()),
        }
