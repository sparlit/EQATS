"""
TradingOS Live Market Gateway Service.
Centralized live data streaming gateway integrating MT5, FIX, WebSocket, and ECN adapters.
"""

import time
from typing import Any

from utils.real_time_feed import RealTimeMarketFeed


class LiveMarketGateway:
    """
    Centralized Live Market Gateway handling real-time price feeds, feed failover,
    latency diagnostics, and provider status tracking.
    """

    def __init__(self) -> None:
        self.active_provider: str = "WEBSOCKET_PRIMARY"
        self.fallback_providers: list[str] = ["MT5_GATEWAY", "FIX_GATEWAY", "REST_FALLBACK"]
        self.connected: bool = False
        self.market_feed = RealTimeMarketFeed(buffer_size=200)
        self.provider_health: dict[str, dict[str, Any]] = {
            "WEBSOCKET_PRIMARY": {
                "status": "DISCONNECTED",
                "latency_ms": 0.0,
                "packet_loss_percent": 0.0,
            },
            "MT5_GATEWAY": {
                "status": "STANDBY",
                "latency_ms": 0.0,
                "packet_loss_percent": 0.0,
            },
            "FIX_GATEWAY": {
                "status": "STANDBY",
                "latency_ms": 0.0,
                "packet_loss_percent": 0.0,
            },
        }

    def connect(self, provider: str | None = None) -> bool:
        """Establishes connection to specified or default primary provider."""
        target_provider = provider or self.active_provider
        self.active_provider = target_provider
        self.connected = True
        if target_provider in self.provider_health:
            self.provider_health[target_provider]["status"] = "CONNECTED"
        return True

    def disconnect(self) -> None:
        """Disconnects gateway feeds."""
        self.connected = False
        if self.active_provider in self.provider_health:
            self.provider_health[self.active_provider]["status"] = "DISCONNECTED"

    def process_live_tick(
        self, symbol: str, bid: float, ask: float, rtt_ms: float = 12.0
    ) -> dict[str, Any]:
        """Ingests live tick from upstream feed and records performance telemetry."""
        if not self.connected:
            self.connect()

        tick = self.market_feed.record_tick(symbol, bid, ask, rtt_ms)
        if self.active_provider in self.provider_health:
            self.provider_health[self.active_provider]["latency_ms"] = rtt_ms

        return {
            "status": "PROCESSED",
            "provider": self.active_provider,
            "tick": tick,
            "latency": self.market_feed.get_latency_stats(),
        }

    def failover_to_secondary(self) -> str:
        """Executes failover to next available secondary provider."""
        for provider in self.fallback_providers:
            if provider != self.active_provider:
                old_provider = self.active_provider
                if old_provider in self.provider_health:
                    self.provider_health[old_provider]["status"] = "DEGRADED"
                self.active_provider = provider
                if provider not in self.provider_health:
                    self.provider_health[provider] = {
                        "status": "CONNECTED",
                        "latency_ms": 0.0,
                        "packet_loss_percent": 0.0,
                    }
                else:
                    self.provider_health[provider]["status"] = "CONNECTED"
                return provider
        return self.active_provider

    def get_gateway_status(self) -> dict[str, Any]:
        """Returns unified gateway health telemetry."""
        latency_stats = self.market_feed.get_latency_stats()
        is_fresh = self.market_feed.is_feed_fresh()
        return {
            "connected": self.connected,
            "active_provider": self.active_provider,
            "providers": self.provider_health,
            "latency": latency_stats,
            "feed_fresh": is_fresh,
            "timestamp": time.time(),
        }


global_live_market_gateway = LiveMarketGateway()
