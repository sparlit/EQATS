# Integration Blueprint for Polymarket Bot into eqats

## Overview
Integrate the Polymarket prediction market data engine, LLM signal generator, and risk controls into the eqats quantitative trading platform.

## Modules

### Data Engines
- eqats/src/engines/data/polymarket.rs: Fetches real‑time market data from Polymarket API (REST + WebSocket).
- Provides normalized MarketData structs (id, question, best_bid, best_ask, volume, timestamp).
- Optionally persists snapshots to a time‑series database (e.g., InfluxDB) via eqats' storage abstraction.

### Signal & Execution Logic
- eqats/src/engines/signal/llm_signal.rs: Calls OpenAI ChatCompletion API with market context to produce a trading signal (Signal { direction: Buy/Sell, strength: f64 }).
- eqats/src/engines/execution/polymarket_executor.rs: Uses the Polymarket SDK to place limit/market orders based on signals.
- Includes order‑management lifecycle (open, amend, cancel).

### Risk Engineering
- eqats/src/engines/risk/polymarket_risk.rs: Implements position sizing (Kelly), max notional per market, daily loss limits, and Telegram alerts.
- Exposes a RiskCheck function that returns Allow or Reject with reason.

## Data Flow
1. PolymarketDataEngine streams market updates.
2. LLMSignalEngine consumes latest market snapshot + news feed → signal.
3. RiskEngine validates signal → adjusted size.
4. PolymarketExecutor submits order to Polymarket.
5. Execution reports feed back to risk and data engines for position updates.

## Configuration
- API keys for Polymarket, OpenAI, Telegram stored in eqats' secrets manager.
- Feature flags to enable/disable LLM or Telegram.

## Testing
- Unit tests with mocked HTTP responses (using wiremock or mockito).
- Integration test against Polymarket testnet (if available).

## Deployment
- Compile as part of eqats Rust core; Python bindings expose PolymarketDataEngine via PyO3 for strategy scripts.

## Future Work
- Add support for multiple prediction markets.
- Replace LLM with local fine‑tuned model for latency‑critical paths.
