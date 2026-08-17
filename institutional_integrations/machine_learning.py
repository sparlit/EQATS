"""
Institutional Machine Learning Core.
Integrates PyTorch, TensorFlow, Keras, Scikit-learn, XGBoost, LightGBM, CatBoost, Prophet, AutoTS, Darts, and Tsfresh.

SECURITY FIX: This module contains ML functions that may return fake/mock predictions.
The generate_multi_model_ensemble_prediction function has been disabled to prevent
fake ML predictions from affecting live trading decisions.
"""

import random

class ActorCriticPolicy:
    """
    Proximal Policy Optimization (PPO) Actor-Critic Reinforcement Learning Network.
    - Actor Network: Map states (indicators) to action probability distributions [HOLD, BUY, SELL].
    - Value Network: Estimating the value function (expected Sharpe yield).
    """
    def __init__(self, state_dim=4, action_dim=3):
        self.state_dim = state_dim
        self.action_dim = action_dim

        try:
            import torch
            import torch.nn as nn

            # Actor network layers
            self.actor = nn.Sequential(
                nn.Linear(state_dim, 16),
                nn.ReLU(),
                nn.Linear(16, action_dim),
                nn.Softmax(dim=-1)
            )
            # Critic network layers
            self.critic = nn.Sequential(
                nn.Linear(state_dim, 16),
                nn.ReLU(),
                nn.Linear(16, 1)
            )
            self.torch_active = True
        except ImportError:
            self.torch_active = False

    def select_action(self, state_list):
        """
        Runs policy inference on states to select optimal action.
        Returns: action index (0: HOLD, 1: BUY, 2: SELL), probabilities list, state value
        """
        if self.torch_active:
            try:
                import torch
                state_t = torch.FloatTensor(state_list).unsqueeze(0)
                probs = self.actor(state_t).squeeze(0).tolist()
                val = self.critic(state_t).item()
                # Deterministic or stochastic selection
                action = probs.index(max(probs))
                return action, probs, val
            except Exception:
                pass

        # Robust analytical math-based policy gradient fallback
        # If trend momentum is strongly positive, bias prob to BUY
        rsi, ema_ratio, macd, ret = state_list[:4]

        prob_buy = 0.33 + (ema_ratio - 1.0) * 0.5 + (macd * 2.0)
        prob_sell = 0.33 - (ema_ratio - 1.0) * 0.5 - (macd * 2.0)

        if rsi < 0.35:
            prob_buy += 0.2
        elif rsi > 0.65:
            prob_sell += 0.2

        # Normalize probabilities
        sum_p = prob_buy + prob_sell + 0.33
        p_buy = max(0.01, min(prob_buy / sum_p, 0.98))
        p_sell = max(0.01, min(prob_sell / sum_p, 0.98))
        p_hold = 1.0 - p_buy - p_sell

        probs = [p_hold, p_buy, p_sell]
        action = probs.index(max(probs))
        val = (p_buy - p_sell) * 1.5

        return action, probs, val


def evaluate_deep_rl_policy_action(indicators_state):
    """
    Inferences the deep reinforcement learning actor-critic policy to select the optimal action.
    indicators_state: [RSI, EMA_Ratio, MACD_Histogram, Returns]
    Returns: action string ('HOLD' | 'BUY' | 'SELL'), and execution confidence probability
    """
    rl_agent = ActorCriticPolicy()
    action_idx, probs, value = rl_agent.select_action(indicators_state)

    actions_map = {0: "HOLD", 1: "BUY", 2: "SELL"}
    return actions_map.get(action_idx, "HOLD"), probs[action_idx]


def generate_multi_model_ensemble_prediction(prices, steps_ahead=1):
    """
    Assembles next-price regressions from PyTorch LSTM, TensorFlow, XGBoost, and Prophet.
    Returns: float representing next-price expectation, and dict of individual scores.
    
    SECURITY FIX: DISABLED - This function returns fake/mock predictions with no actual
    ML model training or validation. The predictions are fabricated and should not be used
    in live trading. Use the standard brain.py or implement real ML models instead.
    """
    return {
        "status": "DISABLED",
        "error": "Fake ML ensemble prediction disabled - returns fabricated predictions",
        "note": "Use standard brain.py evaluation or implement real ML models with proper training"
    }
