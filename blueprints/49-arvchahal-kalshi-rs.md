# Integration Blueprint: kalshi-rs → eqats

## Overview

`kalshi-rs` is a fully‑featured, strongly‑typed Rust SDK for the public Kalshi API. It mirrors the official Python SDK, providing synchronous‑like async interfaces for market data, order execution, and account management. The crate is built on Tokio (async runtime), reqwest (HTTP client), and serde (JSON (de)serialization).

## Mapping to eqats Domains

### Data Engines
- **Market Data Ingestion**
  - `client.get_all_markets(&query)` – retrieve active/inactive markets with pagination.
  - `client.get_orderbook(&ticker, depth?)` – fetch level‑2 order book.
  - `client.get_trades(&ticker, params?)` – historical trade data.
  - `client.get_candlesticks(&ticker, resolution, start_time, end_time?)` – OHLCV candles.
  - **WebSocket Streaming** – subscribe to `orderbook`, `trade`, and `fill` channels for real‑time updates; ideal for feeding eqats’ feature store or online learning pipelines.
- **Account State**
  - `client.get_balance()` and `client.get_positions()` – provide current cash and exposure, useful for risk‑adjusted signal generation.

### Signal & Execution Logic
- **Order Execution**
  - `client.create_order(&CreateOrderRequest { ticker, action, side, count, type_, yes_price, no_price, ... })` – place limit or market orders.
  - `client.cancel_order(&order_id)` – cancel resting orders.
  - `client.edit_order(&order_id, &EditOrderRequest)` – adjust price or size.
  - `client.get_order(&order_id)` – query order status for post‑trade analysis.
- **Portfolio Queries**
  - `client.get_positions()` – retrieve current holdings for position‑sizing logic.
  - `client.get_fills()` – access execution history for performance metrics.
- **Async‑First Design**
  - All calls are `async fn` and integrate naturally with eqats’ Tokio‑based event loop, enabling non‑blocking order submission while processing market data streams.

### Risk Engineering
- The SDK itself does **not** provide risk‑limit engines, volatility‑adjusted sizing, or real‑time risk monitors.
- Risk‑related data can be sourced from the portfolio/positions endpoints (`get_balance`, `get_positions`, `get_fills`) and then processed within eqats’ risk‑engineering layer (e.g., applying VaR, max‑drawdown, or position‑limit checks).
- For true risk limits (e.g., max notional per ticker, daily loss limits), eqats would need to implement its own risk service that consumes the account data provided by kalshi-rs.

## Integration Steps for eqats

1. **Add Dependency**
   ```toml
   # eqats/Cargo.toml
   kalshi-rs = "0.5"   # check latest version on crates.io
   ```
2. **Initialize Client**
   ```rust
   use kalshi_rs::{KalshiClient, Account};
   use std::env;

   #[tokio::main]
   async fn main() -> Result<(), Box<dyn std::error::Error>> {
       let api_key_id = env::var("KALSHI_API_KEY_ID")?;
       let account = Account::from_file("kalshi_private.pem", api_key_id)?;
       let client = KalshiClient::new(account);
       // client now ready for data & trading calls
   }
   ```
3. **Market Data Feed**
   - Spawn a Tokio task that subscribes to the desired WebSocket channels (orderbook, trades).
   - Normalize incoming messages into eqats’ internal market‑data format and push to the feature store.
4. **Signal Generation**
   - Use REST endpoints (`get_all_markets`, `get_candlesticks`) for batch feature calculation (e.g., rolling volatility, momentum).
   - Combine with real‑time WS updates for low‑latency signals.
5. **Order Execution**
   - When a signal triggers, build a `CreateOrderRequest` and call `client.create_order(&req).await?`.
   - Track order IDs in eqats’ order‑management system; use `client.get_order` or WS `fill` events for status updates.
6. **Risk Monitoring**
   - Periodically call `client.get_balance()` and `client.get_positions()` to compute current exposure.
   - Feed these metrics into eqats’ risk‑engineering module to enforce limits or adjust position sizes.
7. **Error Handling & Retry**
   - The SDK returns `Result<T, KalshiError>` mirroring the API’s error codes; wrap calls in eqats’ retry/backoff logic as needed.

## Benefits
- **Feature Parity** – Direct access to >50 Kalshi endpoints ensures eqats can leverage the full breadth of the exchange.
- **Strong Typing** – Rust’s compile‑time safety reduces bugs in order formatting and response parsing.
- **Async‑Native** – Fits seamlessly into eqats’ Tokio‑based architecture, avoiding blocking threads.
- **Well‑Documented** – Examples and quickstart guide in the repository accelerate onboarding.

## Limitations to Consider
- No built‑in risk‑limit or sizing functions; these must be implemented upstream.
- WebSocket implementation follows Kalshi’s spec; handling reconnects and backpressure is the responsibility of the integrating service.
- Tests may hit the live API; ensure a sandbox or test‑net is used during CI to avoid unintended trades.

By integrating `kalshi-rs` as the data‑ingestion and execution layer, eqats gains a reliable, low‑latency bridge to the Kalshi prediction markets while retaining full control over signal generation, risk management, and higher‑order strategy logic in Rust.