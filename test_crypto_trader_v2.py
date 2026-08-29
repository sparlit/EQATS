"""
Unit and Integration Tests for CryptoTrader V2 Engine.
"""

import pytest

from institutional_integrations.crypto_trader_v2_engine import (
    CryptoTraderV2Engine,
    OBISignalType,
    OrderBookLevel,
    OrderBookDepthPayload,
)


def test_crypto_trader_obi_ratio_calculation():
    engine = CryptoTraderV2Engine(obi_buy_threshold=0.75)
    bids = [OrderBookLevel(100.0, 80.0)]
    asks = [OrderBookLevel(101.0, 20.0)]

    ratio = engine.calculate_obi_ratio(bids, asks)
    assert ratio == 0.80


def test_crypto_trader_obi_scalper_entry_and_tp_sl_trigger():
    engine = CryptoTraderV2Engine(obi_buy_threshold=0.75, take_profit_pct=0.20, stop_loss_pct=0.15)

    # 1. Entry Payload (80% bids -> BUY)
    entry_payload = OrderBookDepthPayload(
        symbol="BTCUSDT",
        bids=[OrderBookLevel(50000.0, 80.0)],
        asks=[OrderBookLevel(50010.0, 20.0)],
    )
    sig_type, price, reason = engine.evaluate_order_book_tick(entry_payload)
    assert sig_type == OBISignalType.BUY
    assert price == 50010.0
    assert engine.state.position_open is True

    # 2. Hold Payload (price unchanged)
    hold_payload = OrderBookDepthPayload(
        symbol="BTCUSDT",
        bids=[OrderBookLevel(50010.0, 50.0)],
        asks=[OrderBookLevel(50020.0, 50.0)],
    )
    sig_type2, price2, reason2 = engine.evaluate_order_book_tick(hold_payload)
    assert sig_type2 == OBISignalType.NONE
    assert engine.state.position_open is True

    # 3. Take Profit Payload (+0.30% gain -> SELL)
    tp_payload = OrderBookDepthPayload(
        symbol="BTCUSDT",
        bids=[OrderBookLevel(50165.0, 50.0)],  # +0.31% gain
        asks=[OrderBookLevel(50175.0, 50.0)],
    )
    sig_type3, price3, reason3 = engine.evaluate_order_book_tick(tp_payload)
    assert sig_type3 == OBISignalType.SELL
    assert engine.state.position_open is False


def test_crypto_trader_market_sentiment_evaluator():
    engine = CryptoTraderV2Engine()

    # Extreme Panic -> BUY
    res_panic = engine.evaluate_market_sentiment(15.0, ["Bitcoin crashes 10%"])
    assert res_panic.signal == OBISignalType.BUY
    assert "CAPITULATION" in res_panic.classification

    # Extreme Euphoria -> SELL
    res_euphoria = engine.evaluate_market_sentiment(85.0, ["Bitcoin hits all-time high"])
    assert res_euphoria.signal == OBISignalType.SELL
    assert "EUPHORIA" in res_euphoria.classification
