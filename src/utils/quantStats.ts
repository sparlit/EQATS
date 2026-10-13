/**
 * TradingOS Quantitative Statistics Utilities (TypeScript Interface).
 */

export interface BollingerBandsResult {
  upper: number;
  middle: number;
  lower: number;
  bandwidth: number;
  percent_b: number;
  std_dev: number;
}

export function calculateStandardDeviation(values: number[]): number {
  if (!values || values.length < 2) return 0.0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / values.length;
  return Math.sqrt(Math.max(0.0, variance));
}

export function calculateBollingerBands(
  prices: number[],
  period: number = 20,
  numStd: number = 2.0
): BollingerBandsResult | null {
  if (!prices || prices.length < period || period <= 0) return null;
  const window = prices.slice(-period);
  const middle = window.reduce((a, b) => a + b, 0) / period;
  const stdDev = calculateStandardDeviation(window);
  const upper = middle + numStd * stdDev;
  const lower = middle - numStd * stdDev;
  const bandwidth = middle !== 0 ? (upper - lower) / middle : 0.0;
  const percentB = upper - lower !== 0 ? (prices[prices.length - 1] - lower) / (upper - lower) : 0.5;

  return {
    upper,
    middle,
    lower,
    bandwidth,
    percent_b: percentB,
    std_dev: stdDev,
  };
}

export function calculateRSI(prices: number[], period: number = 14): number {
  if (!prices || prices.length < period + 1 || period <= 0) return 50.0;
  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < prices.length; i++) {
    const diff = prices[i] - prices[i - 1];
    if (diff > 0) {
      gains.push(diff);
      losses.push(0.0);
    } else {
      gains.push(0.0);
      losses.push(Math.abs(diff));
    }
  }
  if (gains.length < period) return 50.0;
  let avgGain = gains.slice(0, period).reduce((a, b) => a + b, 0) / period;
  let avgLoss = losses.slice(0, period).reduce((a, b) => a + b, 0) / period;
  if (avgLoss === 0) return avgGain > 0 ? 100.0 : 50.0;
  for (let i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
  }
  if (avgLoss === 0) return 100.0;
  const rs = avgGain / avgLoss;
  return 100.0 - 100.0 / (1.0 + rs);
}
