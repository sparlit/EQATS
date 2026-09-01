from typing import Any
"""
Unit and Integration Tests for Superalgos Trading Stages Engine.
"""
from typing import Any
from datetime import datetime, timedelta
import pytest
from institutional_integrations.superalgos_trading_engine import SuperalgosTradingStagesEngine, StageType, TriggerStatus

from institutional_integrations.superalgos_trading_engine import (
    SuperalgosTradingStagesEngine,
    StageType,
    TriggerStatus,
)


def test_superalgos_trading_stages_lifecycle() -> None:
    engine = SuperalgosTradingStagesEngine(initial_balance=100000.0)
    now = datetime(2026, 7, 16, 12, 0, 0)
    trig = engine.evaluate_trigger_stage(True)
    assert trig == TriggerStatus.ON
    assert engine.current_stage == StageType.OPEN_STAGE
    pos = engine.execute_open_stage(symbol='BTCUSDT', side='BUY', entry_price=50000.0, size=1.0, stop_loss=49000.0, take_profit=52000.0, open_time=now)
    assert pos.symbol == 'BTCUSDT'
    assert engine.current_stage == StageType.MANAGE_STAGE
    stage_hold = engine.evaluate_manage_stage(current_price=51000.0)
    assert stage_hold == StageType.MANAGE_STAGE
    stage_close = engine.evaluate_manage_stage(current_price=52100.0)
    assert stage_close == StageType.CLOSE_STAGE
    closed_pos = engine.execute_close_stage(exit_price=52100.0, close_time=now + timedelta(hours=2))
    assert closed_pos.realized_pnl == 2100.0
    assert engine.current_stage == StageType.TRIGGER_STAGE
    metrics = engine.get_episode_metrics()
    assert metrics.total_episodes == 1
    assert metrics.winning_episodes == 1
    assert metrics.win_rate == 100.0
    assert metrics.total_realized_pnl == 2100.0
