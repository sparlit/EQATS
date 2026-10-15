import json
from unittest.mock import MagicMock, patch

import pytest
from expressoptionchain.option_chain import (
    OptionChainCreator,
    OptionChainFetcher,
    is_ist_market_session_active,
    round_to_ist_tick,
)


def test_round_to_ist_tick():
    assert round_to_ist_tick(100.02) == 100.0
    assert round_to_ist_tick(100.03) == 100.05
    assert round_to_ist_tick(-10.0) == 0.0


def test_is_ist_market_session_active():
    res = is_ist_market_session_active()
    assert isinstance(res, bool)


def test_option_chain_fetcher_success():
    mock_redis = MagicMock()
    mock_data = json.dumps({"trading_symbol": "HDFCBANK", "expiry": {}})
    mock_redis.hget.return_value = mock_data.encode("utf-8")

    with patch("expressoptionchain.redis_helper.get_redis_instance", return_value=mock_redis):
        fetcher = OptionChainFetcher()
        res = fetcher.get_option_chain("NFO:HDFCBANK")
        assert res["trading_symbol"] == "HDFCBANK"


def test_option_chain_fetcher_not_found():
    mock_redis = MagicMock()
    mock_redis.hget.return_value = None

    with patch("expressoptionchain.redis_helper.get_redis_instance", return_value=mock_redis):
        fetcher = OptionChainFetcher()
        with pytest.raises(Exception, match="Option chain of NFO:INVALID not found"):
            fetcher.get_option_chain("NFO:INVALID")


def test_option_chain_fetcher_get_option_chains():
    mock_redis = MagicMock()
    mock_data = json.dumps({"trading_symbol": "HDFCBANK"})
    mock_redis.hget.return_value = mock_data.encode("utf-8")

    with patch("expressoptionchain.redis_helper.get_redis_instance", return_value=mock_redis):
        fetcher = OptionChainFetcher()
        res = fetcher.get_option_chains(["NFO:HDFCBANK", "NFO:HDFCBANK"])
        assert len(res) == 2


def test_option_chain_creator_base_and_underlying():
    mock_redis = MagicMock()
    mock_redis.hget.return_value = b"1500.50"

    with patch("expressoptionchain.redis_helper.get_redis_instance", return_value=mock_redis), patch(
        "expressoptionchain.option_chain.KiteConnector"
    ):
        creator = OptionChainCreator(kite_secrets={"api_key": "test"})
        token_info = {
            "exchange": "NFO",
            "name": "HDFCBANK",
            "segment": "NFO",
            "lot_size": 550,
        }
        base = creator.get_option_chain_base(token_info, "23-02-2023")

        assert base["trading_symbol"] == "HDFCBANK"
        assert base["exchange"] == "NFO"
        assert base["segment"] == "NFO"
        assert base["underlying_value"] == 1500.50
        assert base["lot_size"] == 550
        assert "23-02-2023" in base["expiry"]


def test_option_chain_creator_underlying_value_index_returns_none():
    mock_redis = MagicMock()

    with patch("expressoptionchain.redis_helper.get_redis_instance", return_value=mock_redis), patch(
        "expressoptionchain.option_chain.KiteConnector"
    ):
        creator = OptionChainCreator(kite_secrets={"api_key": "test"})
        # NIFTY should return None as per implementation
        val = creator.get_underlying_value("NFO", "NIFTY23FEB18000CE")
        assert val is None


def test_option_chain_creator_get_option_detail():
    tick = {
        "depth": {
            "buy": [{"quantity": 100, "price": 10.5}],
            "sell": [{"quantity": 200, "price": 11.0}],
        },
        "last_price": 10.75,
        "last_trade_time": "2023-02-23T10:00:00",
        "exchange_timestamp": "2023-02-23T10:00:00",
        "last_traded_quantity": 50,
        "change": 0.5,
        "oi": 10000,
        "oi_day_high": 12000,
        "oi_day_low": 8000,
        "total_buy_quantity": 5000,
        "ohlc": {"open": 10.0, "high": 11.5, "low": 9.5, "close": 10.0},
        "total_sell_quantity": 6000,
        "volume_traded": 25000,
        "tradable": True,
        "instrument_token": 123456,
    }

    detail = OptionChainCreator.get_option_detail(tick)
    assert detail["bid_quantity"] == 100
    assert detail["bid_price"] == 10.5
    assert detail["ask_quantity"] == 200
    assert detail["ask_price"] == 11.0
    assert detail["premium"] == 10.75
    assert detail["volume"] == 25000
    assert detail["instrument_token"] == 123456
