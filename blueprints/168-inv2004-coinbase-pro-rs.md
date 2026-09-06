# Integration Blueprint for coinbase-pro-rs into eqats

## Overview
`coinbase-pro-rs` is a Rust client for the Coinbase Pro (now Advanced Trade) API offering synchronous, asynchronous, and WebSocket feed interfaces. It provides full access to public market data, private account/trading endpoints, and WebSocket channels (ticker, level2, matches, heartbeat, user, full). The companion `orderbook-rs` crate can be used to maintain a local order‑book snapshot.

## Mapping to eqats Domains

### Data Engines
- **Market Data Ingestion** – REST endpoints for products, currencies, and time; WebSocket feed for real‑time ticker, level2, matches, heartbeat, user, and full channels.
- **Order‑Book Storage** – Integrate with `orderbook-rs` to build and persist a local Level2/L3 book from the WebSocket feed.
- **Historical Data** – Use paginated REST calls (though pagination is not yet implemented in the crate, it can be added) to fetch historic candles/trades for backtesting.

### Signal & Execution Logic
- **Private API Access** – Authentication via API key/secret/passphrase enables:
  - Account balances and ledger (`/accounts`)
  - Order lifecycle: place, cancel, list orders (`/orders`)
  - Execution reports: fills (`/fills`)
  - Deposits/withdrawals listing
  - Fee schedule and user profile
- **Order Execution** – Directly send limit/market/stop orders through the sync or async client; async version works naturally with Tokio‑based event loops in eqats.
- **Strategy Hooks** – WebSocket `matches` and `user` channels provide real‑time execution notices and account updates that can feed signal generation or execution logic.

### Risk Engineering
- **Native Risk Features** – The crate does not expose risk‑limit or position‑sizing utilities.
- **Building Risk Controls** – Leverage private account data (balances, held amounts) and order status to implement:
  - Max position size checks
  - Leverage/margin monitoring
  - Daily loss limits
  - Order‑size throttling based on account equity
  - Real‑time risk monitoring via WebSocket `user` channel (account updates) and `matches` channel (filled size).

## Integration Steps

1. **Add Dependency**
   ```toml
   [dependencies]
   coinbase-pro-rs = "0.7.1"
   orderbook-rs = "0.3"   # optional, for local book
   tokio = { version = "1", features = ["full"] }
   futures = "0.3"
   ```

2. **Create a Market Data Engine**
   - Instantiate `Public<ASync>` (or `Public<Sync>`) for REST polling.
   - Spawn a Tokio task that connects `WSFeed::connect` to desired product(s) and channels (`[ChannelType::Ticker, ChannelType::Level2]`).
   - Feed incoming messages into an `orderbook-rs` book or a custom storage layer (e.g., TimescaleDB, Redis).

3. **Create an Execution Engine**
   - Build a `Private<ASync>` client with API credentials.
   - Implement functions:
     - `place_order(params) -> Result<OrderId, Error>`
     - `cancel_order(order_id) -> Result<(), Error>`
     - `get_fills(...)` for P&L calculation.
   - Use the async client inside eqats’ strategy loop; await responses non‑blockingly.

4. **Risk Layer**
   - Periodically call `get_accounts()` or listen to the `user` WebSocket channel to update equity.
   - Apply risk rules before sending new orders (e.g., reject if notional > max_notional).
   - Log risk events; optionally expose metrics via Prometheus.

5. **Testing & Deployment**
   - Use the sandbox URLs (`SANDBOX_URL`, `WS_SANDBOX_URL`) for end‑to‑end tests.
   - Leverage existing `cargo test` suite to ensure no regressions.
   - Deploy as part of eqats’ Rust service binaries; the crate compiles to native code with no external runtime beyond Tokio.

## Benefits
- **Low Latency** – Async/WebSocket path avoids HTTP round‑trips for real‑time data.
- **Type Safety** – Rust’s strong typing reduces runtime errors in critical trading paths.
- **Modularity** – Separate sync/async clients allow eqats to choose blocking or event‑driven architectures.
- **Community Maintained** – Active crate with docs and examples reduces integration effort.

## Limitations & Mitigations
- **Pagination Missing** – Implement custom pagination using `before`/`after` endpoints if historic depth needed.
- **No Built‑In Risk Controls** – Develop risk modules in eqats using the data provided.
- **WebSocket Reconnection** – The crate provides a basic connect; add reconnection logic with exponential backoff as needed.

## Conclusion
By wrapping `coinbase-pro-rs` in eqats’ data‑engine, execution‑engine, and risk‑engine abstractions, the project gains a production‑grade, low‑latency gateway to Coinbase Pro’s REST and WebSocket APIs while retaining full control over strategy logic and risk management in Rust.