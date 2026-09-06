# Integration Blueprint for rust-trailer into eqats

## Overview
`rust-trailer` is a Rust library providing exchange API wrappers for Binance, Bittrex, and Kucoin, along with a CLI tool for manual trading and early-stage bot trading.

## Feature Mapping

### Data Engines
- **Exchange API Wrappers**: Provide real-time market data (ticker, order book, trades) from supported exchanges. Can be used as a data ingestion layer in eqats to feed market data engines.

### Signal & Execution Logic
- **CLI Tool (`trade-cli`)**: Enables manual order placement and basic bot trading logic. In eqats, this could be wrapped as an execution adapter or used to prototype signal-driven order execution strategies.

### Risk Engineering
- **No native risk management components**. Risk controls (position sizing, limits, monitoring) would need to be added separately in eqats when integrating this library.

## Integration Steps
1. **Add Dependency**: Include `rust-trailer` as a crate in the eqats Rust workspace.
2. **Data Layer**: Create eqats data engine adapters that call the library's market data endpoints and normalize outputs to eqats' internal market data format.
3. **Execution Layer**: Expose the CLI's order‑sending functions (or directly use the library's order placement APIs) as eqats execution agents. Wrap them in eqats' execution interface to allow strategy modules to submit orders.
4. **Risk Layer**: Since the library lacks risk features, implement eqats' risk engineering modules (e.g., risk limits, volatility‑based sizing) around the execution calls.
5. **Testing**: Use the provided CLI to manually verify connectivity and order placement before integrating into automated strategies.
6. **Deployment**: Build the eqats binary with the `rust-trailer` feature enabled; ensure the CLI binary is available if manual intervention is required.

## Benefits
- Quick access to three major crypto exchanges with minimal boilerplate.
- Rust‑native performance and safety align with eqats' language choice.
- CLI offers a low‑friction entry point for testing and manual overrides.

## Considerations
- The library is noted as superseded by `cryptotrader-core`; evaluate long‑term maintenance.
- Missing advanced order types, websocket streams, and risk controls; these would need to be supplemented within eqats.