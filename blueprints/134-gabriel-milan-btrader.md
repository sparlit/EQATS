# Integration Blueprint for bTrader Features into eqats

## Overview
bTrader is a Rust‑based triangle arbitrage bot for Binance. Its core strengths lie in low‑latency market data ingestion, a simple JSON‑config driven strategy, and optional Telegram alerts. These can be leveraged to enhance eqats’ data engine, signal/execution layer, and risk management.

## Data Engines
- **Market Data Feed**: Use binance-rs to subscribe to Binance WebSocket streams for ticker/order‑book data, mirroring bTrader’s real‑time ingestion. This can replace or supplement eqats’ current data connectors.
- **Configuration Management**: Adopt bTrader’s JSON config file format (exchange, trading pairs, min profit, Telegram settings) as an optional profile loader for eqats, enabling quick strategy switches.
- **Containerized Deployment**: Re‑use the Dockerfile/run command (`docker run --net host -v $(pwd)/config.json:/config.json gabrielmilan/btrader`) to provide a ready‑to‑run eqats container for development/testing.

## Signal & Execution Logic
- **Triangle Arbitrage Detector**: Port the arbitrage detection loop (calculate synthetic rates across three pairs, compare to direct pair, emit signal when profit > threshold) into eqats’ signal generation module.
- **Order Execution Wrapper**: Reuse the Binance order‑placement logic (market/limit orders with nonce handling) to execute the triangular route atomically (or as close as possible) within eqats’ execution engine.
- **Telegram Alerting**: Integrate the Telegram bot token/user‑ID logic to send eqats notifications on trade execution, signal discovery, or risk events.

## Risk Engineering
- **Current Gap**: bTrader does not expose explicit risk limits (position size, max daily loss, rate‑limit handling). eqats can add a risk layer on top of the imported strategy:
  - Configurable max notional per triangle.
  - Daily trade count or volume caps.
  - Latency‑based throttling (pause if ping to Binance > X ms).
  - Optional stop‑loss on cumulative PnL.
- **Monitoring**: Leverage bTrader’s logging and Telegram alerts to feed eqats’ risk dashboard, providing real‑time visibility of arbitrage opportunities and executed trades.

## Implementation Steps
1. Add binance-rs as a dependency in eqats’ Cargo.toml.
2. Create a `btrader_strategy` module that reads a JSON config, subscribes to Binance streams, and emits triangle‑arb signals.
3. Wire the signal output to eqats’ existing execution adapter, reusing the order‑placement code from bTrader.
4. Extend eqats’ risk manager with the limits described above, using the same config fields.
5. Expose a Docker build target that mirrors bTrader’s `docker run --net host` pattern for low‑latency testing.
6. Add optional Telegram notifier using the same BotFather token/user‑ID flow.

## Expected Benefits
- Low‑latency, battle‑tested market data pipeline.
- Ready‑made triangle arbitrage logic reduces development time.
- Flexible configuration and containerization improve dev‑ops workflow.
- Telegram integration offers immediate operational awareness.
- Risk controls can be layered to satisfy eqats’ safety requirements.
