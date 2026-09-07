# Integration Blueprint for coinsignal into eqats

## Overview
coinsignal is a Rust‑based cryptocurrency analytics stack that ingests market, on‑chain, and price data, computes a wide set of technical indicators, and stores results in Redis (as a lightweight message bus) and InfluxDB for visualization via Grafana.

## Data Engines Integration
- **Ingestion Pipeline**: Replace or complement eqats’ existing data adapters with coinsignal’s `carbonbot-trade` and `carbonbot-misc` containers. They already pull trade ticks from WebSocket feeds, on‑chain transaction data via Infura/Etherscan, and market‑cap data from CoinMarketCap. These can be configured to publish to a shared Redis stream that eqats consumes.
- **Storage Layer**: eqats can subscribe to the same Redis channels used by coinsignal for real‑time tick data, while persisting long‑term series into InfluxDB (already used by coinsignal). This allows unified historical storage without duplicating pipelines.
- **Schema Mapping**: Map coinsignal’s measurement names (e.g., `trade_price`, `volume`, `gas_price`, `cmc_price`) to eqats’ canonical market‑data schema; add a translation layer in eqats’ ingest service.

## Signal & Execution Logic Integration
- **Indicator Library**: The coinsignal backend implements a reusable Rust indicator crate (e.g., moving averages, RSI, Bollinger Bands, MACD). Export this crate as a dependency or expose its functions via a gRPC/REST endpoint that eqats can call.
- **Signal Generation**: Use the indicator outputs as features in eqats’ strategy engine. For example, a strategy could trigger when RSI < 30 and price > EMA20, using data supplied by coinsignal.
- **Visualization & Debugging**: Leverage the existing Grafana dashboard (frontend) to monitor indicator values alongside eqats’ strategy performance metrics, facilitating rapid iteration.
- **Execution Hook**: While coinsignal does not place orders, its indicator service can be invoked by eqats’ execution module just before order submission to apply last‑minute filters (e.g., volatility‑based position scaling).

## Risk Engineering Integration
- No native risk‑limits or position‑sizing logic is present in coinsignal. Risk management should remain within eqats’ risk engine, consuming the same data and indicator feeds.

## Deployment Considerations
- Run the coinsignal crawler, backend, and frontend containers alongside eqats services in a Docker‑Compose or Kubernetes stack, sharing the same Redis and InfluxDB instances.
- Secure API keys (ETHERSCAN_API_KEY, FULL_NODE_URL, CMC_API_KEY) via a shared secret store (e.g., Vault or Kubernetes secrets) used by both systems.
- The frontend’s Grafana can be re‑branded to show eqats‑specific panels while retaining the indicator visualizations.

## Summary
By integrating coinsignal’s robust data ingestion and indicator computation layers, eqats gains a ready‑made, low‑latency pipeline for crypto market data and a rich set of technical signals, allowing the team to focus on strategy logic, order execution, and advanced risk management.