# Integration Blueprint: dynasty into eqats

## Overview
The dynasty repository provides a cross‑platform native desktop application for spot trading on Binance. Its core functionality consists of a Binance API client (REST and WebSocket) that delivers real‑time market data, account information, and order submission capabilities. Integrating this client into eqats would give the framework access to reliable Binance data feeds and execution endpoints while preserving eqats's modular architecture.

## Domain Mapping

### Data Engines
- **Binance Spot market data (REST/WebSocket)** – provides ticker, order book, klines, and user‑stream updates.
- **Account balance retrieval** – supplies current asset balances for risk calculations.

### Signal & Execution Logic
- **Order placement (limit/market)** – enables sending new orders via the Binance API.
- **Position management** – tracks open orders and fills to maintain a consistent view of the portfolio.
- **Trade execution** – handles order lifecycle (submit, cancel, modify) and reports execution results.

### Risk Engineering
- No explicit risk‑management features are described in the README; risk controls would need to be implemented separately in eqats's RiskEngine layer.

## Integration Steps
1. **Add dependency** – Include dynasty as a Git dependency in Cargo.toml.
2. **Expose client** – Create a thin Rust wrapper (DynastyBinanceClient) that implements eqats's DataEngine and SignalExecutor traits.
3. **DataEngine implementation** – Map dynasty’s WebSocket streams to eqats's market‑data feed (ticker, order book, candles).
4. **SignalExecutor implementation** – Translate eqats’s order requests into dynasty’s Binance API calls, handling responses and errors.
5. **Python/PyO3 bindings** – Use PyO3 to expose the wrapper functions to the eqats Python layer, enabling strategy scripts to subscribe to data and place orders.
6. **Testing** – Run unit tests against a mock Binance endpoint; optionally run integration tests against Binance testnet.

## Risks & Considerations
- The desktop GUI components of dynasty are not required for eqats and can be omitted.
- Ensure API keys are managed securely through eqats's credential vault.
- Version compatibility: track dynasty’s releases to avoid breaking changes.

## Expected Outcome
After integration, eqats will be able to consume live Binance spot market data and execute orders through a battle‑tested native client, while strategy developers continue to work in Python/PyO3.
