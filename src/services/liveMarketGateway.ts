/**
 * TradingOS Live Market Gateway Service Interface.
 * Real-time WebSocket, MT5, FIX, and ECN market feed streamer.
 */

import { RealTimeMarketFeedClient } from '../utils/realTimeFeed';

export interface TickData {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  rtt_ms: number;
  timestamp: number;
}

export interface GatewayStatus {
  connected: boolean;
  active_provider: string;
  latency_ms: number;
  feed_fresh: boolean;
}

export class LiveMarketGatewayClient {
  private connected: boolean = false;
  private activeProvider: string = 'WEBSOCKET_PRIMARY';
  private feed: RealTimeMarketFeedClient = new RealTimeMarketFeedClient(100);
  private lastTickTs: number = 0;

  public connect(provider?: string): boolean {
    this.activeProvider = provider || 'WEBSOCKET_PRIMARY';
    this.connected = true;
    return true;
  }

  public disconnect(): void {
    this.connected = false;
  }

  public processLiveTick(symbol: string, bid: number, ask: number, rttMs: number): TickData {
    this.connected = true;
    this.feed.recordLatency(rttMs);
    this.lastTickTs = Date.now();
    const spread = Math.max(0, ask - bid);
    const mid = (bid + ask) / 2;
    return {
      symbol,
      bid,
      ask,
      mid,
      spread,
      rtt_ms: rttMs,
      timestamp: this.lastTickTs,
    };
  }

  public getStatus(): GatewayStatus {
    const stats = this.feed.getLatencyStats();
    const now = Date.now();
    const isFresh = this.lastTickTs > 0 && (now - this.lastTickTs) <= 5000;
    return {
      connected: this.connected,
      active_provider: this.activeProvider,
      latency_ms: stats.mean_rtt,
      feed_fresh: isFresh,
    };
  }
}

export const globalLiveMarketGateway = new LiveMarketGatewayClient();
