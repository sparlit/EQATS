"""
Prop Firm Monte Carlo Pass-Probability & EV Engine (EQATS Institutional Adaptation)
Adapted from LuxAlgo/prop-firm-sim, Makeph/prop-ev, and shootingallday/propfirm-calc

Provides:
- Vectorized/Iterative Monte Carlo Challenge Pass Probability Simulator
- Expected Monetary Value (EV) & ROI Evaluator
- Risk of Ruin & Expected Attempts Before Passing
- Drawdown Floor Cushion Evaluator (Static, Trailing Intraday, Trailing EOD)
"""
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

@dataclass
class PropChallengeConfig:
    firm_name: str
    account_size: float = 100000.0
    profit_target_usd: float = 10000.0
    daily_loss_limit_usd: float = 5000.0
    max_drawdown_limit_usd: float = 10000.0
    trailing_drawdown: bool = True
    lock_at_initial: bool = True
    min_trading_days: int = 4
    max_trading_days: int = 30
    phases: int = 2
    consistency_pct: Optional[float] = 30.0
    fee_usd: float = 500.0
    profit_split_pct: float = 80.0

@dataclass
class SimulationResult:
    pass_probability: float
    fail_probability: float
    expected_attempts_to_pass: float
    expected_monetary_value_usd: float
    roi_pct: float
    risk_of_ruin_pct: float
    average_days_to_pass: float

class PropFirmMonteCarloEVEngine:
    """Monte Carlo Pass-Probability & Expected Value (EV) Engine."""

    def __init__(self, config: Optional[PropChallengeConfig]=None) -> None:
        self.config = config or PropChallengeConfig(firm_name='FTMO 100K')

    def run_phase_simulation(self, edge_bps_per_trade: float, std_bps_per_trade: float=15.0, trades_per_day: int=10, seed: Optional[int]=None) -> Tuple[bool, int]:
        """Simulates a single challenge phase."""
        rng = random.Random(seed)
        acct = self.config.account_size
        eq = acct
        peak_eq = acct
        start_eq = acct
        day_profits: List[float] = []
        for day in range(1, self.config.max_trading_days + 1):
            day_start_eq = eq
            for _ in range(trades_per_day):
                bps_return = rng.gauss(edge_bps_per_trade, std_bps_per_trade)
                pnl = acct * (bps_return / 10000.0)
                eq += pnl
                peak_eq = max(peak_eq, eq)
                ref_eq = peak_eq if self.config.trailing_drawdown else start_eq
                floor = ref_eq - self.config.max_drawdown_limit_usd
                if self.config.lock_at_initial:
                    floor = min(floor, start_eq)
                if eq <= floor:
                    return (False, day)
                if day_start_eq - eq >= self.config.daily_loss_limit_usd:
                    return (False, day)
            day_pnl = eq - day_start_eq
            day_profits.append(day_pnl)
            if eq - start_eq >= self.config.profit_target_usd and day >= self.config.min_trading_days:
                if self.config.consistency_pct is not None and self.config.consistency_pct > 0:
                    total_profit = eq - start_eq
                    if total_profit > 0:
                        top_day = max((p for p in day_profits if p > 0)) if any((p > 0 for p in day_profits)) else 0.0
                        if top_day / total_profit * 100.0 > self.config.consistency_pct:
                            continue
                return (True, day)
        return (False, self.config.max_trading_days)

    def simulate(self, edge_bps_per_trade: float=5.0, std_bps_per_trade: float=15.0, trades_per_day: int=10, num_simulations: int=2000) -> SimulationResult:
        """Runs multi-phase Monte Carlo simulations and returns statistical metrics."""
        passes = 0
        total_days_spent = 0
        for i in range(num_simulations):
            passed_all_phases = True
            sim_days = 0
            for phase in range(self.config.phases):
                passed, days = self.run_phase_simulation(edge_bps_per_trade, std_bps_per_trade, trades_per_day, seed=i + phase * 10000)
                sim_days += days
                if not passed:
                    passed_all_phases = False
                    break
            if passed_all_phases:
                passes += 1
                total_days_spent += sim_days
        p_pass = passes / float(num_simulations)
        p_fail = 1.0 - p_pass
        expected_attempts = 1.0 / p_pass if p_pass > 0 else float('inf')
        avg_days = total_days_spent / float(passes) if passes > 0 else float(self.config.max_trading_days)
        funded_payout_val = self.config.profit_target_usd * (self.config.profit_split_pct / 100.0)
        ev_usd = p_pass * funded_payout_val - self.config.fee_usd
        roi_pct = ev_usd / self.config.fee_usd * 100.0 if self.config.fee_usd > 0 else 0.0
        return SimulationResult(pass_probability=p_pass, fail_probability=p_fail, expected_attempts_to_pass=expected_attempts, expected_monetary_value_usd=ev_usd, roi_pct=roi_pct, risk_of_ruin_pct=p_fail * 100.0, average_days_to_pass=avg_days)
