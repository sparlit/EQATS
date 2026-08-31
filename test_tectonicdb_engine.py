import pytest
from institutional_integrations.tectonicdb_engine import TectonicDBEngine

def test_tectonicdb_pack_unpack_roundtrip():
    engine = TectonicDBEngine(magic_number=9500001)
    sample_ticks = [
        {
            "timestamp_ns": 1700000000000000000,
            "bid_price": 100.50,
            "ask_price": 100.55,
            "bid_size": 10.0,
            "ask_size": 15.0,
            "trade_price": 100.52,
            "trade_volume": 5.0,
        },
        {
            "timestamp_ns": 1700000000100000000,
            "bid_price": 100.52,
            "ask_price": 100.57,
            "bid_size": 12.0,
            "ask_size": 18.0,
            "trade_price": 100.55,
            "trade_volume": 2.0,
        },
        {
            "timestamp_ns": 1700000000200000000,
            "bid_price": 100.48,
            "ask_price": 100.53,
            "bid_size": 8.0,
            "ask_size": 20.0,
            "trade_price": 100.50,
            "trade_volume": 10.0,
        },
    ]

    packed = engine.pack_ticks(sample_ticks)
    assert isinstance(packed, bytes)
    assert len(packed) > 0

    unpacked = engine.unpack_ticks(packed)
    assert len(unpacked) == 3
    assert unpacked[0]["magic_number"] == 9500001
    assert unpacked[0]["timestamp_ns"] == 1700000000000000000
    assert abs(unpacked[0]["bid_price"] - 100.50) < 1e-4

def test_tectonicdb_filter_time_range():
    engine = TectonicDBEngine(magic_number=9500001)
    ticks = [
        {"timestamp_ns": 100, "bid_price": 10.0, "ask_price": 10.1, "bid_size": 1, "ask_size": 1, "trade_price": 10.0, "trade_volume": 1},
        {"timestamp_ns": 200, "bid_price": 10.1, "ask_price": 10.2, "bid_size": 1, "ask_size": 1, "trade_price": 10.1, "trade_volume": 1},
        {"timestamp_ns": 300, "bid_price": 10.2, "ask_price": 10.3, "bid_size": 1, "ask_size": 1, "trade_price": 10.2, "trade_volume": 1},
    ]

    filtered = engine.filter_time_range(ticks, start_ns=150, end_ns=250)
    assert len(filtered) == 1
    assert filtered[0]["timestamp_ns"] == 200
