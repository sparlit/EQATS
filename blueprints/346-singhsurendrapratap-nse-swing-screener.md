# eqats Integration Blueprint

## Overview
This document outlines how the NSE swing screener could be integrated into the eqats trading system. Due to the unavailability of the source repository, only a conceptual integration is described.

## Components
- **Data Engine**: Fetch NSE OHLCV data via API or CSV.
- **Signal & Execution Logic**: Compute SMA and RSI to generate swing trading signals.
- **Risk Engineering**: Use ATR for stop‑loss and position sizing.

## Data Flow
1. Acquire OHLCV data.
2. Calculate technical indicators (SMA20, RSI14, ATR14).
3. Generate Buy/Sell signals based on price vs SMA and RSI thresholds.
4. Determine stop‑loss (2×ATR) and position size (fixed fractional).
5. Emit orders to the execution layer.

## Integration Approach
A Rust module would expose a SwingScreener struct callable from Python via PyO3. Unit tests would validate signal generation and risk calculations.
