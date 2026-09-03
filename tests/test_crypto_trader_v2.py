"""
Unit and Integration Tests for CryptoTrader V2 Engine.
"""

from typing import Any

import pytest

from institutional_integrations.crypto_trader_v2_engine import (
    CryptoTraderV2Engine,
    OBISignalType,
    OrderBookDepthPayload,
    OrderBookLevel,
)


def test_crypto_trader_obi_ratio_calculation() -> None:
    engine = CryptoTraderV2Engine(obi_buy_threshold=0.75)
    bids = [OrderBookLevel(100.0, 80.0)]
    asks = [OrderBookLevel(101.0, 20.0)]
    ratio = engine.calculate_obi_ratio(bids, asks)
    assert ratio == 0.8


def test_crypto_trader_obi_scalper_entry_and_tp_sl_trigger() -> None:
    engine = CryptoTraderV2Engine(obi_buy_threshold=0.75, take_profit_pct=0.2, stop_loss_pct=0.15)
    entry_payload = OrderBookDepthPayload(
        symbol="BTCUSDT", bids=[OrderBookLevel(50000.0, 80.0)], asks=[OrderBookLevel(50010.0, 20.0)],
    )
    sig_type, price, reason = engine.evaluate_order_book_tick(entry_payload)
    assert sig_type == OBISignalType.BUY
    assert price == 50010.0
    assert engine.state.position_open is True
    hold_payload = OrderBookDepthPayload(
        symbol="BTCUSDT", bids=[OrderBookLevel(50010.0, 50.0)], asks=[OrderBookLevel(50020.0, 50.0)],
    )
    sig_type2, price2, reason2 = engine.evaluate_order_book_tick(hold_payload)
    assert sig_type2 == OBISignalType.NONE
    assert engine.state.position_open is True
    tp_payload = OrderBookDepthPayload(
        symbol="BTCUSDT", bids=[OrderBookLevel(50165.0, 50.0)], asks=[OrderBookLevel(50175.0, 50.0)],
    )
    sig_type3, price3, reason3 = engine.evaluate_order_book_tick(tp_payload)
    assert sig_type3 == OBISignalType.SELL
    assert engine.state.position_open is False


def test_crypto_trader_market_sentiment_evaluator() -> None:
    engine = CryptoTraderV2Engine()
    res_panic = engine.evaluate_market_sentiment(15.0, ["Bitcoin crashes 10%"])
    assert res_panic.signal == OBISignalType.BUY
    assert "CAPITULATION" in res_panic.classification
    res_euphoria = engine.evaluate_market_sentiment(85.0, ["Bitcoin hits all-time high"])
    assert res_euphoria.signal == OBISignalType.SELL
    assert "EUPHORIA" in res_euphoria.classification
