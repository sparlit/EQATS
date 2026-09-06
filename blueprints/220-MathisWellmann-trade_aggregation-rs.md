# Integration Blueprint for trade_aggregation-rs into eqats

## Overview
The `trade_aggregation-rs` crate provides a high‑performance, modular trade‑aggregation engine that turns raw trade streams into user‑defined candles. Its core abstractions are:
- **AggregationRule** – defines when a candle closes (time, volume, tick, price‑movement, etc.).
- **CandleComponent** – defines how a single field of a candle is updated (OHLCV, VWAP, entropy, etc.).
- **ModularCandle** – a struct that aggregates components; the `Candle` derive macro auto‑generates getters and the required `update`/`reset` methods.
- **GenericAggregator** – ties a rule, a candle type, and an input trade type (`TakerTrade`) together, producing candles incrementally.

Because the crate is completely generic over the trade type, it can ingest any market‑data format that implements the simple `TakerTrade` trait (price, size, side, timestamp). This makes it a perfect fit for eqats’ data‑engine layer, where we need to normalize heterogeneous exchange feeds into a common candle representation for downstream strategy and risk modules.

## Proposed Integration Points

### 1. Data Ingestion Layer
- Wrap each exchange’s raw trade WebSocket/REST adapter to produce objects that satisfy `TakerTrade`.
- Feed these objects into a `GenericAggregator<EqatsCandle, MyRule, ExchangeTrade>` where `EqatsCandle` is a candle struct defined with the components needed by eqats strategies (e.g., OHLCV + VWAP + entropy).
- The aggregator can run in a dedicated async task, emitting candles via an async channel or a message bus (e.g., Apache Kafka) for consumption by strategy and risk services.

### 2. Candle Design for eqats
- Define a candle struct using the `#[derive(Candle)]` macro, selecting components:
  ```rust
  #[derive(Debug, Default, Clone, Candle)]
  struct EqatsCandle {
      open: Open,
      high: High,
      low: Low,
      close: Close,
      volume: Volume,
      vwap: WeightedPrice,
      entropy: Entropy,
      trade_count: NumTrades,
  }
  ```
- The macro generates `open()`, `high()`, … getters and the `ModularCandle` implementation, keeping boilerplate minimal.

### 3. Rule Selection
- Use built‑in rules for common needs:
  - `TimeRule::new(M1, TimestampResolution::Millisecond)` for regular‑time candles.
  - `VolumeRule` for volume‑bars (useful for futures).
  - `RelativePriceRule` for Renko‑style bricks when strategies rely on price‑movement thresholds.
- Custom rules (e.g., volatility‑based, order‑flow imbalance) can be added by implementing `AggregationRule` and plugged in without touching the aggregator.

### 4. Back‑testing & Replay
- Because the aggregator works on any iterator of trades, historical CSV or Parquet trade dumps can be processed in batch mode to produce identical candles as the live pipeline—facilitating strategy validation.

### 5. Operational Considerations
- The crate is `no_std`‑compatible (not explicitly stated but likely) and designed for low‑latency; it avoids dynamic allocation inside the hot loop.
- Error handling is simple: `update` returns `Option<Candle>`; the caller decides what to do with `None` (no candle yet).
- Metrics can be gathered by wrapping the aggregator or exposing component internals (e.g., tracking update latency).

## Benefits for eqats
- **Decoupling**: Market‑data ingestion becomes independent of strategy logic; strategies consume candles directly.
- **Flexibility**: New candle fields or alternative aggregation rules can be added without refactoring existing code.
- **Performance**: The Rust implementation is allocation‑free in the hot path, suitable for high‑frequency tick processing.
- **Reusability**: The same aggregation core can serve both live trading and historical back‑testing, ensuring consistency.

## Risks & Mitigations
- **Feature Gap**: The crate does not include execution or risk‑management features; these must remain in eqats’ existing modules.
- **Learning Curve**: Teams need to understand the trait‑based design; provide internal wrappers and examples.
- **Dependency Management**: Ensure the crate’s version is pinned and its `Cargo.toml` features are audited for security.

## Example Snippet (eqats integration)
```rust
use trade_aggregation::{
    candle_components::{Close, High, Low, Open, Volume, WeightedPrice, Entropy, NumTrades},
    rules::TimeRule,
    Aggregator, GenericAggregator,
    TakerTrade,
};

#[derive(Debug, Default, Clone, Candle)]
struct EqatsCandle {
    open: Open,
    high: High,
    low: Low,
    close: Close,
    volume: Volume,
    vwap: WeightedPrice,
    entropy: Entropy,
    trade_count: NumTrades,
}

struct BinanceTrade { /* implements TakerTrade */ }

fn main() {
    let rule = TimeRule::new(M1, TimestampResolution::Millisecond);
    let mut agg: GenericAggregator<EqatsCandle, TimeRule, BinanceTrade> =
        GenericAggregator::new(rule, false);

    for trade in binance_trade_stream() {
        if let Some(candle) = agg.update(&trade) {
            // send candle to strategy/risk channels
            send_candle(candle);
        }
    }
}
```

## Conclusion
Integrating `trade_aggregation-rs` equips eqats with a robust, low‑latency, and extensible market‑data engine that can produce any candle format required by strategies, while keeping the core logic isolated and testable.
