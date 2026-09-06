# Integration Blueprint for studiogangster/next-gen-algo-trading-bot into eqats

## Overview
This blueprint outlines how to integrate the most valuable features of the next-gen-algo-trading-bot into the eqats quantitative trading platform (Rust core with Python/PyO3 bindings). The focus is on the **Per-Instrument Parallel Fetching** mechanism, which provides low-latency, scalable data ingestion suitable for eqats' data engine layer.

## Data Engine Integration
- **Parallel Worker Pool**: Each instrument (symbol/timeframe) runs in its own async task, eliminating bottlenecks and respecting rate limits.
- **Redis‑like Cache**: A thread‑safe in‑memory store (shown as a HashMap) mimics Redis TIMESeries for fast upserts and retrievals.
- **Upsert Semantics**: Incoming candles replace existing entries with the same timestamp, guaranteeing corrected/backfilled data is reflected immediately.
- **Partitioned Sync**: The worker loop can be extended with a partition timestamp to coordinate historical and real‑time streams without gaps or overlaps.
- **Scalability**: Adding new instruments merely spawns another worker; the design maps naturally to a Rayon‑style thread pool or a Tokio‑based async scheduler.

## Signal & Execution Logic Integration
- The cached candle data can be consumed by eqats' signal‑generation modules (Python/PyO3) to compute real‑time indicators (e.g., EMA, RSI) and produce trading signals.
- Because the data store is shared via Arc, Python extensions can read the latest candles without extra copying.
- Signal results can be written back into the same store, enabling a tight feedback loop for strategy execution.

## Risk Engineering Integration
- Position‑management logic can subscribe to the same data stream to enforce per‑symbol exposure limits, max‑drawdown checks, and stop‑loss triggers.
- The modular worker architecture allows risk checks to be run in parallel tasks, ensuring low latency.
- Future work: integrate a dedicated risk‑engine module that consumes indicator signals and emits order‑size adjustments.

## Architecture Diagram
mermaid
flowchart TD
    subgraph User
        F[Frontend - Vue.js]
    end
    subgraph API
        B[Backend - FastAPI]
    end
    subgraph Data
        R[Redis - TimeSeries]
    end
    subgraph Compute
        RW[Ray Cluster]
        W1[Worker 1]
        W2[Worker 2]
        Wn[Worker N]
    end
    subgraph Broker
        Z[Zerodha API]
    end

    Z -- Market Data --> RW
    B -- Write/Read Candles --> R
    F -- REST/WebSocket --> B
    B -- Query/Stream Data --> F
    R -- Pub/Sub, TimeSeries --> RW
    RW -- Signal/Indicator Results --> R
    RW --> W1
    RW --> W2
    RW --> Wn
    B -- Task Dispatch --> RW


## Implementation Plan
1. **Add the parallel_fetcher module** (see integration_code) to eqats/src/.
2. **Expose the DataStore via PyO3** so Python strategies can read candles.
3. **Write a thin Python wrapper** that starts the fetcher for a list of symbols and provides an async iterator over new candles.
4. **Integrate with existing eqats signal engine** by feeding the iterator into indicator calculators.
5. **Write unit tests** (already included) and run them with cargo test.
6. **Benchmark** latency and throughput against a Redis baseline.

## Testing
- The provided #[cfg(test)] test spawns two workers, lets them run for three seconds, and verifies that each symbol receives at least one candle.
- Additional tests should validate upsert behavior, partition timestamp handling, and graceful shutdown.

## Conclusion
By adopting the parallel fetching pattern, eqats gains a robust, low‑latency data ingestion layer that mirrors the strengths of the next‑gen‑algo‑trading‑bot while staying within its Rust‑centric architecture.
