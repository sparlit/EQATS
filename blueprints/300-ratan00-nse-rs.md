# Integration Blueprint for nse-rs in eqats

## Overview
The nse-rs crate is an async Rust client that fetches live and historical market data from the National Stock Exchange of India (NSE). It provides equity quotes, index quotes, option chains, futures, intraday/historical candles, polling feeds, and EOD bhavcopy archives. As a pure data acquisition library it maps directly to the Data Engines layer of eqats.

## Integration Steps
1. **Wrap NseClient in a MarketDataService**
   - Create a struct that holds an NseClient instance.
   - Call `init_session()` once during service start‑up.
   - Expose async methods matching eqats’ data‑feed ports: `get_quote(symbol)`, `get_index(symbol)`, `get_option_chain(symbol)`, `get_futures(symbol)`, `get_candles(symbol, interval, start, end)`, `get_bhavcopy(date)`, `poll_quote(symbol, interval, sender)`, `poll_index(symbol, interval, sender)`.
2. **Async Task Handling**
   - Use tokio::spawn to launch polling loops (`poll_quote`/`poll_index`).
   - Push each received quote/index into eqats’ internal event bus (e.g., a broadcast channel).
   - The loops automatically stop when the receiver is dropped, simplifying shutdown.
3. **Caching**
   - Reuse the built‑in script token cache (symbol → charting token) to avoid duplicate HTTP requests.
   - Add a thin LRU cache (e.g., using the `cached` crate) for frequently accessed quotes or option chains if needed.
4. **Error Handling & Retry**
   - nse-rs already retries on 403/decode failures and refreshes cookies (cached 1 hour).
   - Wrap calls in eqats’ retry policy (exponential backoff) and map anyhow::Error to eqats’ domain error type.
5. **Historical Backfill**
   - Use `get_historical_candles` for intraday intervals (1,3,5,15,30,60 minutes) and daily/weekly/monthly to populate eqats’ historical store (TimescaleDB, Parquet, etc.).
   - The interval strings map directly to eqats’ resolution enumeration.

## Signal & Execution Logic
The crate does not generate trading signals or submit orders. In eqats, the MarketDataService will be consumed by:
- Signal generator modules that subscribe to live quote/index/option‑chain streams.
- Execution modules that translate signals into orders via the broker adapters.
Because the data layer is decoupled, you can replace nse-rs with another provider without touching downstream logic.

## Risk Engineering
Risk controls (position limits, margin checks, VaR) are outside the scope of nse-rs. Implement them in eqats’ risk engine using the market data supplied by the wrapper service. The detailed option‑chain and futures feeds enable computation of Greeks, spread values, and other risk metrics upstream.

## Usage Example (pseudo‑code)
```rust
use eqats::market_data::MarketDataService;
use eqats::messaging::MarketEvent;
use tokio::sync::broadcast;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let svc = MarketDataService::new().await?;
    let (tx, _rx) = broadcast::channel(128);
    
    // start polling NIFTY 50 every 3 seconds
    tokio::spawn({
        let tx = tx.clone();
        let mut client = svc.client.clone();
        async move {
            client.poll_quote('NIFTY 50', 3000, tx).await;
        }
    });
    
    // consume events for strategy pipeline
    while let Ok(event) = tx.recv().await {
        // feed into strategy
    }
    Ok(())
}
```

## Deployment Notes
- Add `nse-rs = { git = \"https://github.com/ratan00/nse-rs.git\" }` to eqats’ Cargo.toml.
- Ensure the tokio runtime matches eqats’ (currently tokio 1 with the 'full' feature set).
- The crate builds without OpenSSL, relying on `rustls-tls-native-roots`, which eases cross‑platform compilation.

## Summary
By wrapping nse-rs in a thin async service, eqats obtains a reliable, zero‑API‑key data engine for Indian equities, indices, derivatives, and historical candles. Signal generation, order execution, and risk management remain separate layers, preserving a clean, modular architecture.
