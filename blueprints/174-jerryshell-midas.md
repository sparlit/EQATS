# Integration Blueprint for eqats using jerryshell/midas

## Overview
Midas is a Rust-based moving average trading backtest simulator with an HTTP API, a web UI, and a data spider for index data.

## Data Engines
- **midas-spider**: Can be scheduled to fetch and store index/market data into a local database or file system. eqats could invoke this binary or reuse its data fetching logic to populate its historical data store.
- **midas-http**: Exposes endpoints to retrieve stored market data and backtest results. eqats could treat this as a microservice for data provisioning.

## Signal & Execution Logic
- The core moving average strategy implementation resides in the Rust backend. eqats could:
  - Import the strategy logic as a library (if exposed) or wrap the midas-http service to generate signals.
  - Use the existing backtest engine to validate eqats signal generation before live deployment.
- The web UI (midas-web) built with bun demonstrates interactive parameter tuning; eqats could embed similar UI components for strategy configuration.

## Risk Engineering
- No explicit risk management features are described in the README. Therefore, no direct risk engineering components can be integrated; eqats would need to supply its own risk limits, position sizing, and monitoring layers around midas-generated signals.

## Integration Steps
1. **Data Layer**: Deploy midas-spider as a cron job to pull index data into a shared storage (e.g., PostgreSQL or CSV) that eqats reads.
2. **API Layer**: Run midas-http to serve historical data and moving average calculations via REST endpoints.
3. **Signal Layer**: Have eqats call midas-http to compute moving averages and generate buy/sell signals, or link directly to the Rust strategy code if available.
4. **Execution Layer**: Feed signals into eqats' order execution engine, applying eqats' risk controls.
5. **Monitoring**: Use eqats' own risk monitoring; optionally extend midas-web UI to display eqats performance metrics.

## Considerations
- License: GNU AGPL v3.0 – ensure compliance when integrating.
- Language boundary: Rust core may require FFI or service calls; the web UI uses bun/JavaScript.
- Extensibility: Since midas focuses solely on moving averages, eqats would need to add other signal types and risk modules.