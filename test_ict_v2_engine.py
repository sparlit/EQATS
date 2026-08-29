"""
Unit and Integration Tests for ICT System v2 Engine.
"""

import pytest

from institutional_integrations.ict_system_v2_engine import (
    ICTSystemV2Engine,
    MarketBias,
    PDAZone,
    StructureType,
)


def test_ict_cisd_detection():
    engine = ICTSystemV2Engine()

    candles_bullish = [
        {"open": 1.0850, "high": 1.0860, "low": 1.0810, "close": 1.0820},
        {"open": 1.0820, "high": 1.0830, "low": 1.0800, "close": 1.0805},  # Red candle, open 1.0820
        {"open": 1.0805, "high": 1.0870, "low": 1.0800, "close": 1.0840},  # Green candle, closes 1.0840 > 1.0820 -> Bullish CISD
    ]

    is_cisd, bias = engine.detect_cisd(candles_bullish)
    assert is_cisd is True
    assert bias == MarketBias.BULLISH


def test_ict_smt_divergence():
    engine = ICTSystemV2Engine()

    # Asset A makes Lower Low (1.0700 < 1.0750)
    a_highs = [1.0800, 1.0810, 1.0820, 1.0800, 1.0790]
    a_lows = [1.0780, 1.0760, 1.0750, 1.0740, 1.0700]

    # Asset B makes Higher Low (1.0760 > 1.0740)
    b_highs = [1.0800, 1.0810, 1.0820, 1.0800, 1.0790]
    b_lows = [1.0780, 1.0760, 1.0740, 1.0750, 1.0760]

    smt_res = engine.detect_smt_divergence(a_highs, a_lows, b_highs, b_lows)
    assert smt_res.detected is True
    assert smt_res.bias == MarketBias.BULLISH


def test_ict_pda_zone_classification():
    engine = ICTSystemV2Engine()

    # High 100.0, Low 90.0, EQ 95.0
    pda_discount = engine.calculate_pda_zones(100.0, 90.0, 91.0)
    assert pda_discount.current_zone == PDAZone.DISCOUNT

    pda_premium = engine.calculate_pda_zones(100.0, 90.0, 99.0)
    assert pda_premium.current_zone == PDAZone.PREMIUM


def test_ict_full_evaluation():
    engine = ICTSystemV2Engine()
    candles = [
        {"open": 110.0, "high": 112.0, "low": 108.0, "close": 109.0},
        {"open": 109.0, "high": 110.0, "low": 98.0, "close": 98.5},
        {"open": 98.5, "high": 99.0, "low": 90.0, "close": 90.5},
        {"open": 90.5, "high": 91.5, "low": 85.0, "close": 86.0},   # Red, open 90.5
        {"open": 86.0, "high": 93.0, "low": 84.0, "close": 91.5},   # Closes 91.5 > 90.5 -> Bullish CISD & Discount (High 112, Low 84, EQ 98)
    ]

    res = engine.evaluate(candles, asian_high=105.0, asian_low=95.0, atr=1.0)
    assert res.bias == MarketBias.BULLISH
    assert res.cisd_confirmed is True
    assert res.pda_zone == PDAZone.DISCOUNT
    assert res.ssl_swept is True
    assert res.confidence >= 0.85
