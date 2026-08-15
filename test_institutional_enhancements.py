import pytest
import indicators
import institutional_integrations.smc_ict_engine as smc
import institutional_integrations.trade_memory_protocol as tmp

def test_smc_ict_order_block_and_fvg_detection():
    # Build dummy bar series with bullish displacement
    opens = [1.1000, 1.0990, 1.0980, 1.0970, 1.1050, 1.1100]
    highs = [1.1010, 1.1000, 1.0990, 1.0980, 1.1060, 1.1110]
    lows = [1.0990, 1.0980, 1.0970, 1.0960, 1.1040, 1.1090]
    closes = [1.0990, 1.0980, 1.0970, 1.1050, 1.1090, 1.1100]

    obs = smc.detect_order_blocks(opens, highs, lows, closes)
    assert "bullish_ob" in obs
    assert "bearish_ob" in obs

    fvgs = smc.detect_fair_value_gaps(highs, lows, closes)
    assert "bullish_fvgs" in fvgs
    assert "bearish_fvgs" in fvgs

def test_smc_ict_mss_and_liquidity_sweeps():
    highs = [1.1000, 1.1050, 1.1020, 1.1080, 1.1150]
    lows = [1.0950, 1.0980, 1.0940, 1.1000, 1.1050]
    closes = [1.0980, 1.1020, 1.0960, 1.1060, 1.1120]

    mss = smc.detect_market_structure_shift(highs, lows, closes)
    assert "mss_status" in mss

    sweeps = smc.detect_liquidity_sweeps(highs, lows, closes)
    assert "bsl_sweep" in sweeps
    assert "ssl_sweep" in sweeps

def test_smc_ict_engine_analysis():
    engine = smc.SmartMoneyConceptsEngine()
    history_bars = []
    base_price = 1.1000
    for i in range(30):
        history_bars.append({
            'open': base_price + i * 0.0001,
            'high': base_price + i * 0.0001 + 0.0005,
            'low': base_price + i * 0.0001 - 0.0005,
            'close': base_price + i * 0.0001 + 0.0002
        })

    res = engine.analyze(history_bars)
    assert "bias" in res
    assert res["bias"] in ["BULLISH", "BEARISH", "NEUTRAL"]
    assert 0.0 <= res["confluence_score"] <= 100.0

def test_trade_memory_reflection_protocol():
    proto = tmp.TradeMemoryReflectionProtocol()
    rec = proto.log_reflection(
        ticket=101,
        symbol="EURUSD",
        direction="BUY",
        open_price=1.1000,
        close_price=1.1020,
        profit=20.0,
        reason="TP",
        mfe=0.0025,
        mae=0.0005
    )
    assert rec["is_win"] is True
    assert rec["efficiency_score"] > 0

    summary = proto.get_summary()
    assert summary["total_reflections"] >= 1
    assert summary["win_rate"] == 100.0

def test_indicators_smc_wrapper():
    history_bars = []
    base_price = 1.1000
    for i in range(20):
        history_bars.append({
            'open': base_price,
            'high': base_price + 0.0005,
            'low': base_price - 0.0005,
            'close': base_price + 0.0001
        })

    smc_res = indicators.get_smc_analysis(history_bars)
    assert "order_blocks" in smc_res
    assert "confluence_score" in smc_res
