"""
Unit and Integration Tests for Batch 3 Modules:
Monte Carlo EV, Trading Seatbelt OS, DXTrade Adapter, and Quant Strategies.
"""
from typing import Any
from datetime import datetime, timedelta
import pytest
from institutional_integrations.prop_firm_monte_carlo_ev import PropFirmMonteCarloEVEngine, PropChallengeConfig
from institutional_integrations.trading_seatbelt_engine import TradingSeatbeltEngine, SeatbeltStatus
from institutional_integrations.dxtrade_broker_adapter import DXTradeBrokerAdapter, DXTradeOrderRequest
from institutional_integrations.batch3_quant_strategies import VWAPFadeStrategy, OvernightDriftStrategy, VolatilityExpansionStrategy, EngulfingAtExtremeStrategy, PivotReactionZoneStrategy

def test_monte_carlo_ev_engine() -> None:
    engine = PropFirmMonteCarloEVEngine(PropChallengeConfig(firm_name='FTMO 100K', fee_usd=500.0))
    res = engine.simulate(edge_bps_per_trade=6.0, num_simulations=200)
    assert 0.0 <= res.pass_probability <= 1.0
    assert res.expected_attempts_to_pass >= 1.0
    assert isinstance(res.expected_monetary_value_usd, float)

def test_trading_seatbelt_engine_cooldown_and_scam_detector() -> None:
    seatbelt = TradingSeatbeltEngine(max_daily_trades=5, max_consecutive_losses=2)
    now = datetime(2026, 7, 16, 10, 0, 0)
    seatbelt.record_trade_outcome(is_win=False, timestamp=now)
    cd1 = seatbelt.get_cooldown_status(now)
    assert not cd1.active
    seatbelt.record_trade_outcome(is_win=False, timestamp=now + timedelta(minutes=1))
    cd2 = seatbelt.get_cooldown_status(now + timedelta(minutes=2))
    assert cd2.active
    assert cd2.remaining_seconds > 0
    scam_res = seatbelt.scan_red_flags('Guaranteed profit pass service 100x account flip')
    assert scam_res['is_suspicious'] is True
    assert len(scam_res['red_flags_detected']) > 0

def test_dxtrade_broker_adapter() -> None:
    adapter = DXTradeBrokerAdapter(username='OPERATOR', password='PASSWORD123', account_id='ACC_99')
    assert adapter.authenticate() is True
    summary = adapter.get_account_summary()
    assert summary.is_connected is True
    assert summary.account_id == 'ACC_99'
    req = DXTradeOrderRequest(account_id='ACC_99', symbol='EURUSD', order_type='MARKET', action='BUY', quantity=1.0, price=1.085)
    resp = adapter.submit_order(req)
    assert resp.success is True
    assert resp.status == 'FILLED'
    assert 'DX_ORD_' in resp.order_id

def test_batch3_quant_strategies() -> None:
    vwap_strat = VWAPFadeStrategy(k_entry=1.5, k_stop=2.5)
    sig_vwap = vwap_strat.evaluate(current_price=1.07, vwap=1.08, std_dev=0.005)
    assert sig_vwap.direction == 'BUY'
    assert sig_vwap.strategy_name == 'vwap_fade'
    drift_strat = OvernightDriftStrategy()
    sig_drift = drift_strat.evaluate(current_price=5000.0, atr=25.0)
    assert sig_drift.direction == 'BUY'
    vol_strat = VolatilityExpansionStrategy()
    sig_vol = vol_strat.evaluate(current_price=1.09, upper_keltner=1.085, lower_keltner=1.075, atr=0.003)
    assert sig_vol.direction == 'BUY'
    engulf_strat = EngulfingAtExtremeStrategy()
    sig_engulf = engulf_strat.evaluate(prev_open=1.082, prev_close=1.08, curr_open=1.0795, curr_close=1.083, recent_high=1.09, recent_low=1.079, atr=0.002)
    assert sig_engulf.direction == 'BUY'
    pivot_strat = PivotReactionZoneStrategy()
    sig_pivot = pivot_strat.evaluate(current_price=1.0752, pivot=1.08, r1=1.085, s1=1.075, atr=0.002)
    assert sig_pivot.direction == 'BUY'
