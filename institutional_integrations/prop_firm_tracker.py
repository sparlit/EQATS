"""
Prop Firm MultiPass Challenge Tracker & Risk Guard Engine.
Manages multi-account prop firm challenge rules (FTMO, MFF, FundedNext, Custom),
tracking Phase 1 / Phase 2 / Funded status, profit targets, daily drawdown limits,
minimum trading days, and payout countdowns.
"""
import time
import math
import logging
from typing import Dict, Any, List, Optional
logger = logging.getLogger('PropFirmTracker')
FIRM_PRESETS = {'FTMO': {'p1_target_pct': 10.0, 'p2_target_pct': 5.0, 'max_daily_loss_pct': 5.0, 'max_total_loss_pct': 10.0, 'min_trading_days': 4}, 'MFF': {'p1_target_pct': 8.0, 'p2_target_pct': 5.0, 'max_daily_loss_pct': 5.0, 'max_total_loss_pct': 12.0, 'min_trading_days': 5}, 'FUNDEDNEXT': {'p1_target_pct': 10.0, 'p2_target_pct': 5.0, 'max_daily_loss_pct': 5.0, 'max_total_loss_pct': 10.0, 'min_trading_days': 5}}

class PropFirmChallengeTracker:
    """
    Multi-Account Prop Firm Challenge & Funded Account Tracker.
    """

    def __init__(self, firm: str='FTMO', starting_balance: float=100000.0, phase: int=1) -> None:
        preset = FIRM_PRESETS.get(firm.upper(), FIRM_PRESETS['FTMO'])
        self.firm = firm.upper()
        self.starting_balance = starting_balance
        self.phase = phase
        self.p1_target_pct = preset['p1_target_pct']
        self.p2_target_pct = preset['p2_target_pct']
        self.max_daily_loss_pct = preset['max_daily_loss_pct']
        self.max_total_loss_pct = preset['max_total_loss_pct']
        self.min_trading_days = preset['min_trading_days']

    def evaluate_account_status(self, current_equity: float, current_balance: float, day_start_equity: float, days_traded: int=0) -> Dict[str, Any]:
        target_pct = self.p1_target_pct if self.phase == 1 else self.p2_target_pct if self.phase == 2 else 0.0
        target_amount = self.starting_balance * (target_pct / 100.0)
        target_equity = self.starting_balance + target_amount
        current_profit = current_equity - self.starting_balance
        profit_pct = current_profit / self.starting_balance * 100.0
        target_progress_pct = min(100.0, current_profit / target_amount * 100.0) if target_amount > 0 else 100.0
        daily_loss = day_start_equity - current_equity
        daily_loss_pct = daily_loss / day_start_equity * 100.0 if day_start_equity > 0 else 0.0
        daily_loss_limit_amount = day_start_equity * (self.max_daily_loss_pct / 100.0)
        total_loss = self.starting_balance - current_equity
        total_loss_pct = total_loss / self.starting_balance * 100.0
        total_loss_limit_amount = self.starting_balance * (self.max_total_loss_pct / 100.0)
        daily_breach = daily_loss_pct >= self.max_daily_loss_pct
        total_breach = total_loss_pct >= self.max_total_loss_pct
        target_passed = current_equity >= target_equity and days_traded >= self.min_trading_days if self.phase in (1, 2) else False
        status = 'PASSED' if target_passed else 'FAILED_DAILY_DD' if daily_breach else 'FAILED_TOTAL_DD' if total_breach else 'IN_PROGRESS'
        return {'firm': self.firm, 'phase': self.phase, 'status': status, 'starting_balance': self.starting_balance, 'current_equity': current_equity, 'profit_pct': round(profit_pct, 2), 'target_progress_pct': round(max(0.0, target_progress_pct), 2), 'daily_loss_pct': round(max(0.0, daily_loss_pct), 2), 'max_daily_loss_pct': self.max_daily_loss_pct, 'total_loss_pct': round(max(0.0, total_loss_pct), 2), 'max_total_loss_pct': self.max_total_loss_pct, 'days_traded': days_traded, 'min_trading_days': self.min_trading_days, 'passed': target_passed, 'failed': daily_breach or total_breach}
