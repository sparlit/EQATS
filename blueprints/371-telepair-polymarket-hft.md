# Integration Blueprint for polymarket-hft into eqats

## Purpose
Leverage the polymarket-hft crate's market data clients and policy engine to feed real-time Polymarket data into eqats' signal generation and risk management layers.

## Components
- **Data Ingestion**: Use polymarket-hft's REST/WebSocket clients (Data, Gamma, CLOB, RTDS) to subscribe to market feeds.
- **Storage**: Forward incoming ticks to eqats' time-series store (e.g., TimescaleDB) via the existing archiver abstraction.
- **Signal & Execution**: Deploy the YAML/JSON policy engine as a strategy layer; evaluate policies on each tick and emit actions (orders, notifications).
- **Risk Engineering**: Wrap policy actions with eqats' risk checks (position limits, max drawdown) before execution.

## Integration Steps
1. Add polymarket-hft = "0.0.6" to eqats' Cargo.toml.
2. Create a thin adapter (src/integrations/polymarket_hft.rs) that:
   - Initializes the desired clients.
   - Converts incoming market events into eqats' internal MarketTick struct.
   - Feeds ticks into a PolicyEngine instance.
   - Translates policy actions into eqats' OrderSignal or Notification.
3. Register the adapter as a data source in eqats' dispatcher configuration.
4. Define policy files in eqats/policies/ using the same schema as polymarket-hft.
5. Hook the adapter's output into eqats' risk engine via the RiskGate component.
6. Test end-to-end with the provided CLI examples (cargo run -- data health) and unit tests.

## Safety Notes
- The polymarket-hft crate is pre‑0.1.0; API may break. Pin the version and monitor upstream releases.
- All network calls are asynchronous; integrate with eqats' Tokio runtime.
- Ensure API keys for CoinMarketCap/CoinGecko are set via environment variables as documented.

## Future Work
- Contribute missing risk‑specific policy operators (e.g., max_position) back to polymarket-hft.
- Replace the internal Redis/TimescaleDB usage with eqats' unified storage abstraction.