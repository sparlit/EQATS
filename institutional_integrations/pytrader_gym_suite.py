"""
PyTrader & TradingGym Suite (EQATS Institutional Adaptation)
Adapted from owocki/pytrader and Yvictor/TradingGym (trading_env)

Provides:
- TradingGymRLAdapter: Gym-style Reinforcement Learning environment step evaluator & state vector constructor
- PyTraderDepthAnalyzer: Order book liquidity depth ratio & volume imbalance metrics
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union, Any
import numpy as np

@dataclass
class GymStepResult:
    state_vector: np.ndarray
    reward: float
    done: bool
    info: Dict[str, float]

@dataclass
class DepthAnalysisResult:
    bid_depth_volume: float
    ask_depth_volume: float
    depth_ratio: float
    imbalance_pct: float
    buy_pressure: str

class TradingGymRLAdapter:
    """OpenAI Gym-style Reinforcement Learning Trading Environment Adapter."""

    def __init__(self, initial_balance: float=10000.0, fee_pct: float=0.001) -> None:
        self.initial_balance = initial_balance
        self.fee_pct = fee_pct
        self.balance = initial_balance
        self.position = 0.0
        self.entry_price = 0.0
        self.prev_equity = initial_balance

    def reset(self) -> np.ndarray:
        """Resets environment state."""
        self.balance = self.initial_balance
        self.position = 0.0
        self.entry_price = 0.0
        self.prev_equity = self.initial_balance
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def step(self, action: int, current_price: float, returns_history: List[float]) -> GymStepResult:
        """Executes RL step: action (0 = HOLD, 1 = BUY, 2 = SELL/CLOSE)."""
        if current_price <= 0:
            return GymStepResult(np.zeros(4, dtype=np.float32), 0.0, True, {})
        reward = 0.0
        if action == 1 and self.position == 0.0:
            cost = self.balance * (1.0 - self.fee_pct)
            self.position = cost / current_price
            self.balance = 0.0
            self.entry_price = current_price
        elif action == 2 and self.position > 0.0:
            revenue = self.position * current_price * (1.0 - self.fee_pct)
            self.balance = revenue
            self.position = 0.0
            self.entry_price = 0.0
        current_equity = self.balance + self.position * current_price
        reward = float(np.log(max(1e-05, current_equity) / max(1e-05, self.prev_equity)))
        self.prev_equity = current_equity
        norm_equity = current_equity / self.initial_balance
        pos_ratio = 1.0 if self.position > 0 else 0.0
        price_ret = float(returns_history[-1]) if returns_history else 0.0
        vol = float(np.std(returns_history[-10:])) if len(returns_history) >= 10 else 0.01
        state = np.array([norm_equity, pos_ratio, price_ret, vol], dtype=np.float32)
        done = bool(current_equity <= self.initial_balance * 0.2)
        return GymStepResult(state_vector=state, reward=round(reward, 6), done=done, info={'equity': round(current_equity, 2), 'position_units': round(self.position, 4)})

class PyTraderDepthAnalyzer:
    """Order Book Depth Ratio and Liquidity Imbalance Analyzer."""

    def analyze_depth(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]], depth_levels: int=10) -> DepthAnalysisResult:
        """Analyzes top N bid/ask levels for volume depth imbalance."""
        if not bids or not asks:
            return DepthAnalysisResult(0.0, 0.0, 1.0, 0.0, 'NEUTRAL')
        top_bids = bids[:depth_levels]
        top_asks = asks[:depth_levels]
        bid_vol = float(sum((vol for price, vol in top_bids)))
        ask_vol = float(sum((vol for price, vol in top_asks)))
        total_vol = bid_vol + ask_vol
        if total_vol <= 0:
            return DepthAnalysisResult(0.0, 0.0, 1.0, 0.0, 'NEUTRAL')
        depth_ratio = bid_vol / max(1e-05, ask_vol)
        imbalance_pct = (bid_vol - ask_vol) / total_vol * 100.0
        if imbalance_pct > 25.0:
            pressure = 'HIGH_BUY'
        elif imbalance_pct < -25.0:
            pressure = 'HIGH_SELL'
        else:
            pressure = 'NEUTRAL'
        return DepthAnalysisResult(bid_depth_volume=round(bid_vol, 2), ask_depth_volume=round(ask_vol, 2), depth_ratio=round(depth_ratio, 2), imbalance_pct=round(imbalance_pct, 2), buy_pressure=pressure)
