/**
 * TradingOS Real-Time Feed Utility Hook and Interface.
 */

export interface LatencyStats {
  mean_rtt: number;
  p50_rtt: number;
  p90_rtt: number;
  p95_rtt: number;
  p99_rtt: number;
  jitter: number;
}

export class RealTimeMarketFeedClient {
  private rttBuffer: number[] = [];
  private bufferSize: number;

  constructor(bufferSize: number = 100) {
    this.bufferSize = bufferSize;
  }

  public recordLatency(rttMs: number): void {
    this.rttBuffer.push(rttMs);
    if (this.rttBuffer.length > this.bufferSize) {
      this.rttBuffer.shift();
    }
  }

  public getLatencyStats(): LatencyStats {
    if (this.rttBuffer.length === 0) {
      return { mean_rtt: 0, p50_rtt: 0, p90_rtt: 0, p95_rtt: 0, p99_rtt: 0, jitter: 0 };
    }
    const sorted = [...this.rttBuffer].sort((a, b) => a - b);
    const n = sorted.length;
    const mean = sorted.reduce((a, b) => a + b, 0) / n;

    let jitter = 0;
    if (this.rttBuffer.length > 1) {
      let diffSum = 0;
      for (let i = 1; i < this.rttBuffer.length; i++) {
        diffSum += Math.abs(this.rttBuffer[i] - this.rttBuffer[i - 1]);
      }
      jitter = diffSum / (this.rttBuffer.length - 1);
    }

    return {
      mean_rtt: mean,
      p50_rtt: sorted[Math.floor(n * 0.5)],
      p90_rtt: sorted[Math.min(n - 1, Math.floor(n * 0.9))],
      p95_rtt: sorted[Math.min(n - 1, Math.floor(n * 0.95))],
      p99_rtt: sorted[Math.min(n - 1, Math.floor(n * 0.99))],
      jitter,
    };
  }
}

export function useRealTimeMarketFeed(bufferSize: number = 100): RealTimeMarketFeedClient {
  return new RealTimeMarketFeedClient(bufferSize);
}
