"""
QuantDinger Grid Trading & Factor Research Engine (EQATS Institutional Adaptation)
Adapted from OpenByteInc/QuantDinger

Provides:
- QuantDingerGridEngine: Arithmetic & Geometric Grid Cell Level Generator, Hit Evaluator, and Grid PnL Reconciler
- QuantDingerFactorResearchEngine: Factor Signal Calculator & Factor Performance Scorer
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np

class GridMode(str, Enum):
    ARITHMETIC = 'ARITHMETIC'
    GEOMETRIC = 'GEOMETRIC'

@dataclass
class GridLevel:
    level_index: int
    price: float
    order_side: str
    executed: bool = False
    fill_price: float = 0.0

@dataclass
class GridState:
    lower_bound: float
    upper_bound: float
    grid_count: int
    grid_mode: GridMode
    grid_levels: List[GridLevel]
    total_grid_profit: float = 0.0
    active_grid_orders: int = 0

@dataclass
class FactorScoreResult:
    factor_name: str
    ic_score: float
    sharpe_ratio: float
    direction: str

class QuantDingerGridEngine:
    """QuantDinger Grid Trading Runtime & Grid Cell Engine."""

    def __init__(self, lower_bound: float=1000.0, upper_bound: float=2000.0, grid_count: int=10, grid_mode: GridMode=GridMode.ARITHMETIC, investment_usd: float=10000.0) -> None:
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.grid_count = grid_count
        self.grid_mode = grid_mode
        self.investment_usd = investment_usd
        self.state = self._initialize_grid()

    def _initialize_grid(self) -> GridState:
        levels = []
        if self.grid_mode == GridMode.ARITHMETIC:
            step = (self.upper_bound - self.lower_bound) / float(self.grid_count)
            prices = [self.lower_bound + i * step for i in range(self.grid_count + 1)]
        else:
            ratio = (self.upper_bound / self.lower_bound) ** (1.0 / float(self.grid_count))
            prices = [self.lower_bound * ratio ** i for i in range(self.grid_count + 1)]
        mid_price = (self.lower_bound + self.upper_bound) / 2.0
        for idx, p in enumerate(prices):
            side = 'BUY' if p < mid_price else 'SELL'
            levels.append(GridLevel(level_index=idx, price=round(p, 4), order_side=side))
        return GridState(lower_bound=self.lower_bound, upper_bound=self.upper_bound, grid_count=self.grid_count, grid_mode=self.grid_mode, grid_levels=levels, total_grid_profit=0.0, active_grid_orders=len(levels))

    def evaluate_grid_hits(self, current_price: float) -> Tuple[List[GridLevel], float]:
        """Evaluates current price against active grid levels and triggers order execution & cell profit reconciliation."""
        executed_levels = []
        grid_pnl_gain = 0.0
        for lvl in self.state.grid_levels:
            if not lvl.executed:
                if lvl.order_side == 'BUY' and current_price <= lvl.price:
                    lvl.executed = True
                    lvl.fill_price = current_price
                    executed_levels.append(lvl)
                elif lvl.order_side == 'SELL' and current_price >= lvl.price:
                    lvl.executed = True
                    lvl.fill_price = current_price
                    executed_levels.append(lvl)
                    matched_buy_lvls = [l for l in self.state.grid_levels if l.executed and l.order_side == 'BUY']
                    if matched_buy_lvls:
                        lowest_buy = min(matched_buy_lvls, key=lambda l: l.fill_price)
                        cell_pnl = (lvl.fill_price - lowest_buy.fill_price) * (self.investment_usd / self.grid_count / lvl.fill_price)
                        grid_pnl_gain += max(0.0, cell_pnl)
                        lowest_buy.executed = False
        self.state.total_grid_profit += grid_pnl_gain
        return (executed_levels, grid_pnl_gain)

class QuantDingerFactorResearchEngine:
    """QuantDinger Factor Signal & Information Coefficient (IC) Research Engine."""

    def evaluate_factor_ic(self, factor_values: List[float], forward_returns: List[float], factor_name: str='MomentumFactor') -> FactorScoreResult:
        """Calculates Information Coefficient (IC) correlation between factor values and forward returns."""
        if not factor_values or not forward_returns or len(factor_values) != len(forward_returns):
            return FactorScoreResult(factor_name, 0.0, 0.0, 'NEUTRAL')
        f_arr = np.array(factor_values)
        r_arr = np.array(forward_returns)
        corr_matrix = np.corrcoef(f_arr, r_arr)
        ic = float(corr_matrix[0, 1]) if corr_matrix.shape == (2, 2) and (not np.isnan(corr_matrix[0, 1])) else 0.0
        mean_ret = float(np.mean(r_arr))
        std_ret = float(np.std(r_arr))
        sharpe = mean_ret / (std_ret + 1e-06) * math.sqrt(252)
        direction = 'BULLISH' if ic > 0.1 else 'BEARISH' if ic < -0.1 else 'NEUTRAL'
        return FactorScoreResult(factor_name=factor_name, ic_score=round(ic, 4), sharpe_ratio=round(sharpe, 2), direction=direction)
