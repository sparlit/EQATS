# Integration Blueprint for eqats: Rust Trading Engine

## Summary
The `trading_engine_rust` repository provides a high‑performance, order‑matching engine written in Rust. Its core components—OrderBook, Limit, MatchingEngine, and TradingPair—can be reused inside the eqats framework to handle market data storage, order matching, and trade execution.

## Data Engines Integration
- **OrderBook as Market‑Data Store**: The engine keeps bids and asks in separate `HashMap` price‑level maps. This structure can replace or complement eqats’ existing market‑data cache for each trading pair, offering O(1) insertion/lookup and efficient price‑level aggregation.
- **Limit Struct**: Encapsulates volume at a price level; useful for pre‑trade analytics (e.g., depth‑of‑market calculations) that eqats can expose via its signal layer.
- **MatchingEngine**: Holds a collection of OrderBooks keyed by `TradingPair`. By feeding eqats’ real‑time market‑data feed (WebSocket, FIX) into the engine’s `add_market` and `place_limit_order` methods, the engine becomes a low‑latency matching layer.
- **Ingestion Pipeline**: eqats’ data‑ingestion adapters can publish raw tick events to a Rust‑based service (via FFI or gRPC) that updates the OrderBook, ensuring the engine stays synchronized with the external market.

## Signal & Execution Logic Integration
- **Limit Order Execution**: The engine’s matching logic fills orders when a bid price ≥ ask price. eqats’ strategy modules can generate limit‑order intents (price, size, side) and send them to the MatchingEngine via a thin Rust wrapper or REST endpoint.
- **Order Lifecycle**: When the engine fills an order, it removes the filled quantity from the OrderBook. eqats can listen to fill callbacks (exposed through the wrapper) to update position tracking, generate execution reports, and trigger downstream risk checks.
- **Multiple Markets**: Support for many `TradingPair` instances enables eqats to run simultaneous strategies across different assets without duplicating matching code.

## Risk Engineering Integration
- The README does not describe explicit risk‑limit or position‑sizing mechanisms. To satisfy eqats’ risk requirements, a thin risk‑layer can be added around the MatchingEngine:
  - **Pre‑trade checks**: Validate order size against max‑notional or max‑position limits before calling `place_limit_order`.
  - **Post‑trade monitoring**: Use fill events to update eqats’ risk engine (e.g., VaR, leverage) and trigger alerts if limits are breached.
  - **Optional extensions**: Implement cancel‑on‑disconnect, order‑rate throttling, or iceberg‑order logic within the Rust service.

## Implementation Steps
1. **Create a Rust service** that exposes:
   - `init_market(base: str, quote: str) -> MarketId`
   - `submit_limit_order(market_id, side, price, qty) -> OrderId`
   - Stream of fill events (price, qty, side, timestamp).
2. **Wrap the service** with eqats’ foreign‑function interface (e.g., using `rustler` for Elixir/NIF, or a gRPC/protobuf layer) so eqats can call it from its main language (likely Python/Elixir).
3. **Configure eqats’ data‑ingestion** to forward real‑time tick data to the Rust service’s market‑data update function.
4. **Route strategy‑generated orders** through the service’s order‑submission API.
5. **Connect fill callbacks** to eqats’ execution‑reporting and risk‑monitoring modules.
6. **Add risk‑checks** (pre‑trade size limits, max‑order‑rate) either in the Rust service or as eqats‑side guards.

## Example (pseudo‑code)
```rust
// Rust service snippet
let engine = MatchingEngine::new();
engine.add_market(TradingPair::new("BTC", "USD"));
let order_id = engine.place_limit_order(
    Side::Buy,
    Price::from(27000),
    Volume::from(1.5),
    "BTC-USD"
);
// Fill events are sent via a callback to eqats
```

By integrating the Rust trading engine as a dedicated matching and market‑data service, eqats gains a battle‑tested, low‑latency core while retaining its flexible strategy and risk frameworks in the host language.