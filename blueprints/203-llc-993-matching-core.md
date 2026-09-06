# Integration Blueprint for matching-core into eqats

## Overview
This blueprint outlines how to incorporate the llc-993/matching-core library into the eqats quantitative trading stack to achieve ultra‑low latency execution, robust persistence, rich order‑type support, and scalable risk management.

## Data Engine Integration
- **Order Book as Market Data Store**: Use `AdvancedOrderBook` (or the `direct_optimized` variant) as the low‑latency, in‑memory limit order book that eqats will query for market data.
- **Memory Efficiency**: Leverage the SOA layout and pre‑allocated order pool to reduce per‑order allocations and garbage‑collection pressure.
- **Persistence**: Integrate the WAL (`journal.rs`) and snapshot (`snapshot.rs`) modules to persist order book state and enable fast recovery after restarts.
- **Zero‑Copy Serialization**: Apply rkyv‑based serialization for efficient inter‑process communication or storage of order book snapshots.
- **Sharding & Parallelism**: Adopt the library’s sharding architecture to run multiple matching engine instances across CPU cores, each with its own order book.
- **ART Index for Price Levels**: Utilize the adaptive radix tree index for rapid price‑level lookups when building market depth feeds.
- **SIMD Batch Matching**: Enable SIMD‑optimized batch matching for processing large bursts of orders (e.g., during market open) with minimal latency.

## Signal & Execution Logic Integration
- **Unified Order Types**: Feed eqats’ trading signals into the matching core via `OrderCommand`, setting `OrderType` to GTC, IOC, FOK, PostOnly, StopLimit, StopMarket, Iceberg, Day, or GTD as needed.
- **Instrument Support**: Populate `CoreSymbolSpecification` with the appropriate `SymbolType` (CurrencyExchangePair, FuturesContract, PerpetualSwap, CallOption, PutOption) to trade spots, futures, perpetuals, and options through the same engine.
- **Advanced Orderbook Selection**: Choose between `naive.rs`, `direct.rs`, `direct_optimized.rs`, or `advanced.rs` based on latency vs. feature‑richness requirements (e.g., use `advanced` for Iceberg and Post‑Only handling).
- **Matching Pipeline**: Invoke the pipeline in `pipeline.rs` and the matching engine in `matching_engine.rs` to convert signals into matcher events (trades, order updates) that eqats can consume for position tracking and PnL calculation.
- **Event Handling**: Iterate over `matcher_events` on `OrderCommand` to receive fill notifications, enabling real‑time update of eqats’ internal state.

## Risk Engineering Integration
- **Pre‑Trade Risk Checks**: Hook eqats’ risk‑management layer into the `risk_engine.rs` module before submitting an `OrderCommand` to the matching core. The risk engine can enforce limits on order size, notional exposure, position limits, and max leverage.
- **Sharded Risk Engines**: Deploy multiple risk engine instances matching the matching engine shards, allowing parallel risk evaluation without becoming a bottleneck.
- **Risk Monitoring**: Expose internal risk metrics (e.g., current position, utilized margin) from the risk engine for eqats’ risk dashboard and alerting system.
- **Dynamic Configuration**: Adjust risk parameters at runtime via the same configuration mechanisms used for `CoreSymbolSpecification` (fees, scales, etc.).

## Build & Deployment
1. Add matching-core as a dependency in eqats’ `Cargo.toml`:
   ```toml
   matching-core = { git = "https://github.com/llc-993/matching-core" }
   ```
2. Build with optimizations:
   ```bash
   cargo build --release
   ```
3. Validate integration by running the provided examples:
   ```bash
   cargo run --example advanced_demo --release
   cargo run --example comprehensive_test --release
   ```
4. For performance verification, execute the benchmarks:
   ```bash
   cargo bench --bench comprehensive_bench
   ```

## Performance Expectations
Based on the repository’s benchmarks:
- **Throughput**: Millions of transactions per second (TPS) and queries per second (QPS) even with 100k+ orders.
- **Latency**: Average latency < 1 µs per order; P99 < 10 µs.
- **Memory Footprint**: Roughly 0.19 MB per 1k orders, scaling linearly.

## Conclusion
By embedding matching-core’s high‑performance matching engine, durable WAL/snapshot storage, extensive order‑type and multi‑instrument support, and sharded risk‑engine capabilities, eqats can achieve institutional‑grade execution speed while maintaining strict risk controls and flexible asset‑class coverage.
