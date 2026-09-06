"""
Tests for Open Interest Live Analysis Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.open_interest_live_analysis_engine import (
    OpenInterestLiveAnalysisEngine,
    OpenInterestLiveAnalysisBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_OPEN_INTEREST_LIVE_ANALYSIS,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_max_pain_and_pcr_momentum_evaluations():
    engine = OpenInterestLiveAnalysisEngine()
    assert engine.magic_number == MAGIC_NUMBER_OPEN_INTEREST_LIVE_ANALYSIS

    strikes = [24000.0, 24500.0, 25000.0, 25500.0]
    call_oi = [10000, 15000, 25000, 5000]
    put_oi = [2000, 8000, 30000, 12000]

    max_pain = engine.compute_max_pain(strikes, call_oi, put_oi)
    assert max_pain == 25000.0

    pcr_hist = [0.95, 1.05, 1.15, 1.25]
    pcr_res = engine.analyze_pcr_momentum(pcr_hist)
    assert pcr_res["pcr_bias"] == "STRONG_BULLISH"
    assert pcr_res["pcr_momentum"] > 0.0


def test_open_interest_live_analysis_broker_adapter():
    adapter = OpenInterestLiveAnalysisBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("OPEN_INTEREST_LIVE_ANALYSIS") == OpenInterestLiveAnalysisBrokerAdapter

    req = SEBIOrderRequest(
        symbol="NIFTY",
        quantity=50,
        price=24950.02,
        order_type="BUY",
        product="NRML",
        exchange="NFO",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.open_interest_live_analysis_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 24950.00
        assert res.ticket.startswith("OILIVE-")
