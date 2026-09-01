"""
Unit and Integration Tests for ICT System v2 Engine.
"""
from typing import Any
import pytest
from institutional_integrations.ict_system_v2_engine import ICTSystemV2Engine, MarketBias, PDAZone, StructureType

def test_ict_cisd_detection() -> None:
    engine = ICTSystemV2Engine()
    candles_bullish = [{'open': 1.085, 'high': 1.086, 'low': 1.081, 'close': 1.082}, {'open': 1.082, 'high': 1.083, 'low': 1.08, 'close': 1.0805}, {'open': 1.0805, 'high': 1.087, 'low': 1.08, 'close': 1.084}]
    is_cisd, bias = engine.detect_cisd(candles_bullish)
    assert is_cisd is True
    assert bias == MarketBias.BULLISH

def test_ict_smt_divergence() -> None:
    engine = ICTSystemV2Engine()
    a_highs = [1.08, 1.081, 1.082, 1.08, 1.079]
    a_lows = [1.078, 1.076, 1.075, 1.074, 1.07]
    b_highs = [1.08, 1.081, 1.082, 1.08, 1.079]
    b_lows = [1.078, 1.076, 1.074, 1.075, 1.076]
    smt_res = engine.detect_smt_divergence(a_highs, a_lows, b_highs, b_lows)
    assert smt_res.detected is True
    assert smt_res.bias == MarketBias.BULLISH

def test_ict_pda_zone_classification() -> None:
    engine = ICTSystemV2Engine()
    pda_discount = engine.calculate_pda_zones(100.0, 90.0, 91.0)
    assert pda_discount.current_zone == PDAZone.DISCOUNT
    pda_premium = engine.calculate_pda_zones(100.0, 90.0, 99.0)
    assert pda_premium.current_zone == PDAZone.PREMIUM

def test_ict_full_evaluation() -> None:
    engine = ICTSystemV2Engine()
    candles = [{'open': 110.0, 'high': 112.0, 'low': 108.0, 'close': 109.0}, {'open': 109.0, 'high': 110.0, 'low': 98.0, 'close': 98.5}, {'open': 98.5, 'high': 99.0, 'low': 90.0, 'close': 90.5}, {'open': 90.5, 'high': 91.5, 'low': 85.0, 'close': 86.0}, {'open': 86.0, 'high': 93.0, 'low': 84.0, 'close': 91.5}]
    res = engine.evaluate(candles, asian_high=105.0, asian_low=95.0, atr=1.0)
    assert res.bias == MarketBias.BULLISH
    assert res.cisd_confirmed is True
    assert res.pda_zone == PDAZone.DISCOUNT
    assert res.ssl_swept is True
    assert res.confidence >= 0.85
