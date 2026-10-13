"""
TradingOS Real-Time Market Feed Hook and Telemetry Buffer.
Implements sliding-window RTT buffers, debounced telemetry updates, and feed quality metrics.
"""

import collections
import time
from typing import Any


class RealTimeMarketFeed:
    """
    High-throughput, latency-aware market feed telemetry manager.
    Manages sliding window RTT latency buffers, jitter calculations, and data freshness tracking.
    """

    def __init__(self, buffer_size: int = 100) -> None:
        self.buffer_size = buffer_size
        self.rtt_buffer: collections.deque = collections.deque(maxlen=buffer_size)
        self.price_cache: dict[str, dict[str, Any]] = {}
        self.last_update_ts: float = time.time()
        self.total_packets_received: int = 0
        self.packet_loss_count: int = 0

    def record_tick(
        self, symbol: str, bid: float, ask: float, rtt_ms: float, sequence_id: int | None = None
    ) -> dict[str, Any]:
        """Records tick update and appends latency measurements."""
        now = time.time()
        self.rtt_buffer.append(rtt_ms)
        self.total_packets_received += 1
        self.last_update_ts = now

        spread = round(max(0.0, ask - bid), 5)
        mid_price = round((bid + ask) / 2.0, 5)

        tick_data = {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid_price,
            "spread": spread,
            "rtt_ms": rtt_ms,
            "timestamp": now,
            "sequence_id": sequence_id,
        }
        self.price_cache[symbol] = tick_data
        return tick_data

    def get_latency_stats(self) -> dict[str, float]:
        """Calculates mean RTT, P50, P90, P95, P99, and jitter."""
        if not self.rtt_buffer:
            return {
                "mean_rtt": 0.0,
                "p50_rtt": 0.0,
                "p90_rtt": 0.0,
                "p95_rtt": 0.0,
                "p99_rtt": 0.0,
                "jitter": 0.0,
            }

        sorted_rtt = sorted(self.rtt_buffer)
        n = len(sorted_rtt)

        mean_rtt = sum(sorted_rtt) / float(n)
        p50 = sorted_rtt[int(n * 0.50)]
        p90 = sorted_rtt[min(n - 1, int(n * 0.90))]
        p95 = sorted_rtt[min(n - 1, int(n * 0.95))]
        p99 = sorted_rtt[min(n - 1, int(n * 0.99))]

        # Jitter as average absolute difference between consecutive RTT samples
        jitter = 0.0
        if n > 1:
            diffs = [
                abs(self.rtt_buffer[i] - self.rtt_buffer[i - 1])
                for i in range(1, len(self.rtt_buffer))
            ]
            jitter = sum(diffs) / float(len(diffs))

        return {
            "mean_rtt": round(mean_rtt, 2),
            "p50_rtt": round(p50, 2),
            "p90_rtt": round(p90, 2),
            "p95_rtt": round(p95, 2),
            "p99_rtt": round(p99, 2),
            "jitter": round(jitter, 2),
        }

    def is_feed_fresh(self, max_stale_seconds: float = 5.0) -> bool:
        """Evaluates whether the market feed data is fresh."""
        return (time.time() - self.last_update_ts) <= max_stale_seconds


def use_real_time_market_feed(buffer_size: int = 100) -> RealTimeMarketFeed:
    """Helper factory function for RealTimeMarketFeed instance."""
    return RealTimeMarketFeed(buffer_size=buffer_size)
