"""
Unit and Integration Tests for Freqtrade Protection Engine.
"""
from typing import Any
from datetime import datetime, timedelta
import pytest
from institutional_integrations.freqtrade_protection_engine import FreqtradeProtectionEngine, LockSide

def test_freqtrade_pair_and_global_locks() -> None:
    engine = FreqtradeProtectionEngine()
    now = datetime(2026, 7, 16, 12, 0, 0)
    assert engine.is_locked('BTC/USDT', now).is_locked is False
    engine.lock_pair('BTC/USDT', now + timedelta(hours=1), 'Manual pause')
    assert engine.is_locked('BTC/USDT', now + timedelta(minutes=30)).is_locked is True
    assert engine.is_locked('ETH/USDT', now + timedelta(minutes=30)).is_locked is False
    assert engine.is_locked('BTC/USDT', now + timedelta(hours=2)).is_locked is False
    engine.lock_pair('*', now + timedelta(hours=2), 'Circuit breaker active')
    assert engine.is_locked('ETH/USDT', now + timedelta(hours=1)).is_locked is True

def test_freqtrade_cooldown_and_stoploss_guard() -> None:
    engine = FreqtradeProtectionEngine()
    now = datetime(2026, 7, 16, 12, 0, 0)
    engine.record_completed_trade('EURUSD', LockSide.LONG, -100.0, True, now)
    engine.record_completed_trade('EURUSD', LockSide.LONG, -150.0, True, now + timedelta(minutes=15))
    cd = engine.evaluate_cooldown_period('EURUSD', now + timedelta(minutes=20), cooldown_minutes=30.0)
    assert cd is not None
    assert 'CooldownPeriod active' in cd.reason
    sl_guard = engine.evaluate_stoploss_guard('EURUSD', now + timedelta(minutes=20), stoploss_limit=2)
    assert sl_guard is not None
    assert 'StoplossGuard' in sl_guard.reason

def test_freqtrade_max_drawdown_protection() -> None:
    engine = FreqtradeProtectionEngine()
    now = datetime(2026, 7, 16, 12, 0, 0)
    dd_lock = engine.evaluate_max_drawdown_protection(12.0, now, max_drawdown_limit_pct=10.0)
    assert dd_lock is not None
    assert dd_lock.symbol == '*'
    assert engine.is_locked('ANY_PAIR', now + timedelta(hours=1)).is_locked is True
