"""
Test Suite for TradingOS Live Market Gateway and Real-Time Feed.
Tests live market tick ingestion, failover, latency metrics, and feed freshness.
"""

from services.live_market_gateway import LiveMarketGateway, global_live_market_gateway
from utils.real_time_feed import RealTimeMarketFeed, use_real_time_market_feed


def test_real_time_market_feed():
    """Tests RealTimeMarketFeed tick recording and latency statistics."""
    feed = use_real_time_market_feed(buffer_size=10)
    assert isinstance(feed, RealTimeMarketFeed)
    assert feed.is_feed_fresh() is True

    # Record ticks
    feed.record_tick("EURUSD", 1.0850, 1.0852, rtt_ms=10.0)
    feed.record_tick("EURUSD", 1.0851, 1.0853, rtt_ms=15.0)
    feed.record_tick("EURUSD", 1.0852, 1.0854, rtt_ms=12.0)

    stats = feed.get_latency_stats()
    assert stats["mean_rtt"] > 0.0
    assert stats["p50_rtt"] > 0.0
    assert stats["jitter"] >= 0.0
    assert feed.is_feed_fresh() is True


def test_live_market_gateway():
    """Tests LiveMarketGateway connection, failover, and status reports."""
    gateway = LiveMarketGateway()
    assert gateway.connected is False

    gateway.connect()
    assert gateway.connected is True
    assert gateway.active_provider == "WEBSOCKET_PRIMARY"

    res = gateway.process_live_tick("GBPUSD", 1.2650, 1.2652, rtt_ms=14.0)
    assert res["status"] == "PROCESSED"
    assert res["tick"]["symbol"] == "GBPUSD"

    # Failover
    new_provider = gateway.failover_to_secondary()
    assert new_provider != "WEBSOCKET_PRIMARY"

    status = gateway.get_gateway_status()
    assert status["connected"] is True
    assert status["feed_fresh"] is True

    gateway.disconnect()
    assert gateway.connected is False


def test_global_live_market_gateway_instance():
    """Tests global singleton LiveMarketGateway instance."""
    assert global_live_market_gateway is not None
    assert global_live_market_gateway.get_gateway_status()["connected"] is False
