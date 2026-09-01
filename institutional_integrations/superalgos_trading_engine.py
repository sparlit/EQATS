"""
Superalgos Algorithmic Trading Stages Engine (EQATS Institutional Adaptation)
Adapted from Superalgos/Superalgos (Projects/Algorithmic-Trading/TS/Bot-Modules/Trading-Bot/Low-Frequency-Trading)

Provides:
- 4-Stage Trading System State Machine:
  1. Trigger Stage (Trigger On / Off condition evaluation)
  2. Open Stage (Position Entry order placement & fill)
  3. Manage Stage (Dynamic SL / TP target management)
  4. Close Stage (Position Exit / Partial Close execution)
- Episode Accounting (Tracks ROI, Win Rate, Max Drawdown, and Duration across episodes)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


class StageType(str, Enum):
    TRIGGER_STAGE = "TRIGGER_STAGE"
    OPEN_STAGE = "OPEN_STAGE"
    MANAGE_STAGE = "MANAGE_STAGE"
    CLOSE_STAGE = "CLOSE_STAGE"


class TriggerStatus(str, Enum):
    OFF = "OFF"
    ON = "ON"


@dataclass
class SuperalgosPosition:
    position_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    entry_price: float
    size: float
    stop_loss: float
    take_profit: float
    open_time: datetime
    close_time: Optional[datetime] = None
    close_price: float = 0.0
    realized_pnl: float = 0.0
    status: str = "OPEN"


@dataclass
class EpisodeMetrics:
    total_episodes: int
    winning_episodes: int
    losing_episodes: int
    total_realized_pnl: float
    win_rate: float
    max_drawdown_pct: float


class SuperalgosTradingStagesEngine:
    """Superalgos 4-Stage Trading Engine & Episode Auditor."""

    def __init__(self, initial_balance: float = 100000.0):
        self.initial_balance = initial_balance
        self.current_stage: StageType = StageType.TRIGGER_STAGE
        self.trigger_status = TriggerStatus.OFF
        self.active_position: Optional[SuperalgosPosition] = None
        self.closed_positions: List[SuperalgosPosition] = []

    def evaluate_trigger_stage(self, trigger_condition: bool) -> TriggerStatus:
        """Stage 1: Evaluates Trigger On/Off conditions."""
        if trigger_condition:
            self.trigger_status = TriggerStatus.ON
            self.current_stage = StageType.OPEN_STAGE
        else:
            self.trigger_status = TriggerStatus.OFF
            self.current_stage: StageType = StageType.TRIGGER_STAGE
        return self.trigger_status

    def execute_open_stage(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: float,
        open_time: datetime,
    ) -> SuperalgosPosition:
        """Stage 2: Executes Position Entry."""
        if self.trigger_status != TriggerStatus.ON:
            raise ValueError("Cannot open stage without Trigger ON status")

        pos_id = f"EP_{len(self.closed_positions) + 1}"
        pos = SuperalgosPosition(
            position_id=pos_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            open_time=open_time,
        )
        self.active_position = pos
        self.current_stage = StageType.MANAGE_STAGE
        return pos

    def evaluate_manage_stage(
        self, current_price: float, new_stop_loss: Optional[float] = None, new_take_profit: Optional[float] = None
    ) -> StageType:
        """Stage 3: Manages Stop Loss and Take Profit levels during position lifetime."""
        if not self.active_position:
            self.current_stage: StageType = StageType.TRIGGER_STAGE
            return self.current_stage

        if new_stop_loss is not None:
            self.active_position.stop_loss = new_stop_loss
        if new_take_profit is not None:
            self.active_position.take_profit = new_take_profit

        # Check exit triggers
        pos = self.active_position
        if pos.side == "BUY":
            if current_price <= pos.stop_loss or current_price >= pos.take_profit:
                self.current_stage = StageType.CLOSE_STAGE
        else:  # SELL
            if current_price >= pos.stop_loss or current_price <= pos.take_profit:
                self.current_stage = StageType.CLOSE_STAGE

        return self.current_stage

    def execute_close_stage(self, exit_price: float, close_time: datetime) -> SuperalgosPosition:
        """Stage 4: Closes active position and records episode metrics."""
        if not self.active_position:
            raise ValueError("No active position to close")

        pos = self.active_position
        pos.close_price = exit_price
        pos.close_time = close_time
        pos.status = "CLOSED"

        if pos.side == "BUY":
            pos.realized_pnl = (exit_price - pos.entry_price) * pos.size
        else:
            pos.realized_pnl = (pos.entry_price - exit_price) * pos.size

        self.closed_positions.append(pos)
        self.active_position = None
        self.trigger_status = TriggerStatus.OFF
        self.current_stage: StageType = StageType.TRIGGER_STAGE
        return pos

    def get_episode_metrics(self) -> EpisodeMetrics:
        """Calculates cumulative session episode performance metrics."""
        total = len(self.closed_positions)
        if total == 0:
            return EpisodeMetrics(0, 0, 0, 0.0, 0.0, 0.0)

        wins = sum(1 for p in self.closed_positions if p.realized_pnl > 0)
        losses = sum(1 for p in self.closed_positions if p.realized_pnl < 0)
        tot_pnl = sum(p.realized_pnl for p in self.closed_positions)
        win_rate = (wins / total) * 100.0

        equity_curve = [self.initial_balance]
        for p in self.closed_positions:
            equity_curve.append(equity_curve[-1] + p.realized_pnl)

        peak = np.maximum.accumulate(equity_curve)
        dd = (peak - equity_curve) / peak * 100.0
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        return EpisodeMetrics(
            total_episodes=total,
            winning_episodes=wins,
            losing_episodes=losses,
            total_realized_pnl=tot_pnl,
            win_rate=win_rate,
            max_drawdown_pct=max_dd,
        )
