# Integration Blueprint: nseta → eqats

## Overview
nseta is a Python library and CLI tool for fetching NSE India market data, computing technical indicators, recognizing candlestick patterns, backtesting strategies, and generating trading signals across equity stocks.

## Data Engines Integration
- **Data Ingestion**: Use nseta’s `get_live_quote()` and `get_historical_data()` functions to pull real‑time and end‑of‑day data directly into eqats’ market data pipeline.
- **Storage Format**: All data is returned as pandas DataFrames, matching eqats’ internal format, enabling zero‑copy conversion.
- **Caching & News**: Leverage nseta’s built‑in caching and news‑headline fetch to enrich eqats’ alternative data store.
- **Implementation**: Wrap these calls in an eqats data‑adapter plugin that registers nseta as a provider for the `NSE` market.

## Signal & Execution Logic Integration
- **Technical Indicators**: Reuse nseta’s indicator calculations (RSI, MACD, Bollinger Bands, etc.) as eqats signal primitives.
- **Pattern Recognition**: Plug nseta’s candlestick pattern detector into eqats’ pattern‑recognition service.
- **Backtesting**: Import nseta’s backtesting engine to evaluate eqats‑generated strategies on historical NSE data before live deployment.
- **Signal Generation**: Expose nseta’s scanner outputs (BUY/SELL based on RSI thresholds, volume spikes, MACD alignment, etc.) as eqats signal events via the internal signal bus.
- **Custom Strategies**: Allow users to write eqats strategy modules that call nseta’s `create_scanner()` or `build_strategy()` functions, then feed the resulting signals into eqats’ order‑execution gateway.
- **Live Scanning**: Run nseta’s background scanner within eqats’ scheduler to continuously emit signals during market hours.

## Risk Engineering Integration
- **Alerts as Risk Monitors**: Map nseta’s console alerts for support/resistance breaches and abnormal volume growth to eqats’ risk‑monitoring hooks, triggering position‑size reductions or stop‑loss orders.
- **Gap**: nseta lacks explicit risk‑limit, position‑sizing, or VaR modules; eqats should supplement these with its own risk‑engine components (e.g., max‑drawdown limits, Kelly sizing).
- **Implementation**: Create a risk‑adapter that subscribes to nseta’s alert channel and forwards risk events to eqats’ risk‑manager for further action.

## Deployment Considerations
- Both projects are Python‑based; nseta can be installed via `pip install nseta` alongside eqats dependencies.
- Docker images already exist for nseta; they can be reused or extended in eqats’ CI/CD pipeline.
- Since nseta is marked as unmaintained, consider forking the repository or vendor‑ing the required modules to ensure long‑term stability within eqats.

## Summary
By integrating nseta’s robust data acquisition and signal‑generation capabilities, eqats gains immediate access to NSE‑specific market data, technical‑analysis tools, and ready‑to‑run scanners, while retaining its own risk‑management and order‑execution frameworks for a complete quantitative trading system.