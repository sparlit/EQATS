# Integration Blueprint for rust-crypto-trader into eqats

## Overview
The rust-crypto-trader repository provides a Rust-based cryptocurrency trading bot targeting the Independent Reserve exchange. Its most valuable component for eqats is the orderbook data engine and spread calculation logic, which can be reused as a market data feed and signal generation module.

## Domain Mapping
- **Data Engines**: Orderbook fetching, configuration loading.
- **Signal & Execution Logic**: Spread calculation, trade signal generation.
- **Risk Engineering**: Currently minimal; can be extended with position sizing and risk limits.

## Integration Plan
1. Add a new data engine module eqats/src/data_engines/independent_reserve.rs that wraps the Independent Reserve public API.
2. Expose a trait ExchangeDataEngine for pluggable backends (real or mock).
3. Provide a utility function calculate_spread for signal generation.
4. Include unit tests using mock data to ensure reliability without network calls.
5. Update eqats/Cargo.toml to add dependencies: reqwest, serde, serde_json.
6. Provide a Python/PyO3 binding (optional) to expose the spread signal to Python strategies.

## Files
- eqats/src/data_engines/independent_reserve.rs – core implementation.
- eqats/src/lib.rs – re-export the module.
- eqats/python/bindings.rs – PyO3 wrapper (if needed).

## Testing
- Unit tests validate spread calculation and mock exchange behavior.
- Integration tests can be added later using a testnet or sandbox.
