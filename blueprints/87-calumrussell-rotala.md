# Integration Blueprint for Rotala into eqats

## Overview
Rotala is a Rust‑based backtesting engine that can operate as a standalone server or be imported as a library. It provides market data handling, strategy execution, and an example implementation (Alator) showing how to plug in custom logic.

## Data Engines Integration
- **Market Data Ingestion & Storage**: Rotala’s core includes data loading and storage mechanisms that can be reused to feed eqats’ data pipeline.
- **Server Mode**: Deploy Rotala as a data service; eqats can query historical candles via HTTP/WebSocket.
- **Library Mode**: Link Rotala directly into eqats Rust components to obtain tick/bar streams without extra networking.

## Signal & Execution Logic Integration
- **Strategy Framework**: Use the pattern shown in Alator: define a struct implementing Rotala’s strategy trait, receive market events, emit signals.
- **Order Simulation**: Rotala’s backtesting engine already simulates order fills, slippage, and latency; eqats can leverage this for offline strategy validation.
- **Live Execution**: When run as a server, Rotala can forward signals to eqats’ execution adapter for real‑time order routing.

## Risk Engineering Integration
- *No explicit risk‑limit or position‑sizing features are described in the Rotala README.* If risk controls are needed, they should be implemented in eqats’ risk layer and fed with data from Rotala.

## Integration Steps
1. Add Rotala as a dependency in eqats’ `Cargo.toml`.
2. Create a thin adapter that implements eqats’ `DataFeed` trait by wrapping Rotala’s market‑data iterator.
3. For strategy development, mirror Alator’s approach: implement Rotala’s `Strategy` trait, plug into eqats’ signal generator.
4. Optionally run Rotala in server mode and configure eqats to consume its HTTP endpoint for historical data.
5. Unit‑test strategies using Rotala’s built‑in backtesting harness before deploying to eqats’ live trading.

## Conclusion
Rotala supplies a solid Rust backtesting foundation that can replace or augment eqats’ current data engine and strategy execution modules, while risk management remains the responsibility of eqats.
