# Integrating kalshi-rust into eqats

## Overview
The `kalshi-rust` crate provides a fully‑featured, asynchronous Rust client for the Kalshi trading API. It can be used by eqats to (1) ingest real‑time and historical market data, (2) execute trading signals via order submission/cancellation, and (3) monitor account‑level risk metrics such as balance and positions.\n
## 1. Data Engine Integration

### Market Data Ingestion
- **Endpoints used**: `GetEvents`, `GetEvent`, `GetMarkets`, `GetTrades`, `GetMarket`, `GetMarketHistory`, `GetMarketOrderBook`, `GetSeries`.
- **Usage in eqats**: Pull the latest order book, recent trades, and historical price series for each market of interest. Feed these streams into eqats’ feature‑engineering pipeline (e.g., calculate mid‑price, volatility, order‑book imbalance).
- **Implementation tip**: Wrap each endpoint in an async Rust function that returns a strongly‑typed struct (as provided by the crate). Use `tokio::select!` or a futures stream to poll multiple markets concurrently.

### Exchange & Reference Data
- **Endpoints**: `GetExchangeSchedule`, `GetExchangeStatus`.
- **Purpose**: Determine market open/close times, holiday calendars, and trading halts—essential for aligning eqats’ signal generation with actual trading windows.

### Portfolio & Account Data
- **Endpoints**: `GetBalance`, `GetFills`, `GetOrders`, `GetPositions`, `GetPortfolioSettlements`.
- **Usage**: Provide eqats with real‑time equity, margin, and position data to compute current exposure, P&L, and to validate that signals respect existing holdings.

## 2. Signal & Execution Logic Integration

### Order Submission
- **Endpoint**: `CreateOrder`.
- **Usage**: When eqats’ signal generator emits a trade idea (e.g., “buy 10 contracts of XYZ at $0.65”), call `CreateOrder` with the appropriate parameters (market ticker, side, quantity, price, order type).

### Order Management
- **Endpoints**: `CancelOrder`, `DecreaseOrder`, `GetOrder`, `GetOrders`.
- **Usage**: Implement eqats’ order‑lifecycle logic: cancel stale orders, reduce size when risk limits are approached, query order status for fill confirmation, and retrieve open orders for reconciliation.

### Batch Operations
- **Supported**: `BatchCancelOrders` (useful for rapid risk‑off scenarios).
- **Not yet supported**: `BatchCreateOrders` – eqats can simulate batching by issuing multiple `CreateOrder` calls concurrently.

### Example Execution Flow (pseudo‑Rust)
```rust
use kalshi::{KalshiClient, NewOrderRequest};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = KalshiClient::new(api_key, api_secret).await?;
    
    // 1. Fetch market data (data engine)
    let order_book = client.get_market_order_book("XYZ").await?;
    let mid_price = (order_book.best_bid + order_book.best_ask) / 2.0;
    
    // 2. Generate signal (eqats logic)
    if mid_price < 0.60 {
        // 3. Submit order (signal & execution)
        let order_req = NewOrderRequest {
            ticker: "XYZ".to_string(),
            side: kalshi::Side::Buy,
            count: 10,
            price: 65, // price in cents
            r#type: kalshi::OrderType::Limit,
            ..Default::default()
        };
        client.create_order(&order_req).await?;
    }
    
    // 4. Monitor balance (risk engineering)
    let balance = client.get_balance().await?;
    if balance.available < 1000 {
        // trigger risk‑off
        client.batch_cancel_orders(vec![]).await?;
    }
    
    Ok(())
}
```

## 3. Risk Engineering Integration

### Exposure Monitoring
- Use `GetBalance` to obtain available cash, collateral, and margin requirements.
- Use `GetPositions` to aggregate current long/short exposure per market.
- Combine these with eqats’ internal risk limits (e.g., max notional per market, max daily loss) to decide whether to allow new orders or to initiate position reduction.

### Limitations
- The library does **not** provide built‑in risk‑limit enforcement or position‑sizing helpers; these must be implemented on the eqats side using the data returned by the above endpoints.
- No direct support for calculating Value‑at‑Risk (VaR) or stress‑testing; eqats would need to compute those internally from the historical data fetched via `GetMarketHistory` and `GetTrades`.

## 4. Deployment Considerations
- Add `kalshi = "0.9.0"` (or latest) to eqats’ `Cargo.toml`.
- Ensure the async runtime (Tokio) matches eqats’ existing runtime to avoid conflicts.
- Handle API authentication securely: store Kalshi API key/secret in eqats’ secret management system and pass them to the client at startup.
- Implement retry/back‑off logic for transient network errors, as the crate returns standard `reqwest` errors.
- Monitor rate limits: Kalshi imposes per‑endpoint limits; eqats should throttle requests accordingly (the crate does not auto‑throttle).

## Conclusion
By wrapping `kalshi-rust` as a data‑engine, execution‑engine, and risk‑monitoring component, eqats can leverage a performant, type‑safe Rust client to access Kalshi’s markets while retaining full control over strategy logic, risk limits, and portfolio management in the higher‑level eqats framework.
