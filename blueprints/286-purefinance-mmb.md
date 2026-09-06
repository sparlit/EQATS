# Integration Blueprint for mmb Features into eqats

## Overview
mmb is a Rust-based trading engine with exchange connectors, strategy automation, and market making capabilities. The following outlines how its most valuable components can be incorporated into the eqats quantitative trading platform.

## Data Engines
- **Exchange Connectors**: mmb provides ready‑made connectors for Binance Spot, Binance USDⓈ-M Futures, Bitmex, Serum, and Interactive Brokers (status indicated by color‑coded badges). These connectors handle WebSocket/REST market data ingestion (order book, ticker, trade streams) and can be reused as eqats data adapters.
- **Configuration**: API keys and secrets are stored in `credentials.toml`. eqats can adopt a similar TOML‑based credential store, mapping each connector to an eqats data engine instance.
- **Implementation Path**: Wrap each mmb connector in an eqats‑compatible adapter that publishes normalized market data to eqats’ internal event bus (e.g., using Apache Arrow or Protobuf). Leverage Rust’s async runtime (Tokio) already present in mmb for low‑latency feeds.

## Signal & Execution Logic
- **Strategy Framework**: mmb separates strategy logic from execution via `config.toml` (strategy parameters) and `example/src` (sample strategies). eqats can import this pattern by defining strategy plugins that read a TOML configuration and expose `on_market_update` and `on_order_event` callbacks.
- **Market Making**: The built‑in market making algorithm (quote generation, inventory management) can be refactored into an eqats signal module that emits limit orders based on mid‑price and spread parameters.
- **Order Execution**: Connectors also provide order placement, cancellation, and status reporting. eqats can reuse these execution adapters, routing signals from its strategy layer to the appropriate connector via a unified execution interface.
- **Integration Steps**:
  1. Extract connector code into a crate `eqats-connector-mmb`.
  2. Define a trait `MarketDataFeed` and `OrderExecutor` that mmb connectors implement.
  3. In eqats strategy runner, instantiate connectors based on `credentials.toml`.
  4. Pass market data updates to strategy plugins; receive order intents and forward them to the executor.

## Risk Engineering
- **Current State**: The README does not detail risk limits, position sizing, or real‑time risk monitoring. Therefore, no direct risk‑engineering features can be pulled from mmb without further investigation.
- **Suggested Approach**: eqats should supplement the mmb‑derived execution layer with its own risk engine (e.g., max‑position, VaR, kill‑switch) that wraps order intents before they reach the executor.

## Conclusion
By adopting mmb’s connector ecosystem and strategy configuration pattern, eqats can rapidly expand its exchange coverage and strategy development workflow. Risk management will need to be added separately, leveraging eqats’ existing risk‑engineering modules.
