# Integration Blueprint: ninjabook → eqats

## Overview
ninjabook is a Rust‑based (with Python bindings) high‑performance order‑book library designed to ingest Level 2 market data and trade events, maintain an internal limit‑order book, and efficiently query the best bid/ask or top‑N levels. Its core value for eqats lies in providing a low‑latency, reliable market‑data engine that can replace or supplement existing data‑ingestion components.

## Data Engines Domain Integration

### 1. Market‑Data Ingestion Layer
- Replace eqats’ current Level 2 parser with ninjabook’s `Orderbook` struct.
- Feed raw Level 2 messages (e.g., from exchange WebSocket or FIX) into ninjabook via its `apply_update`‑style API (as demonstrated in the Rust `hello_world` example).
- The library internally maintains bid/ask maps, ensuring O(log N) updates and constant‑time BBO/top‑N queries.

### 2. Streaming Market Data
- Use ninjabook’s `get_bbo()` and `get_top_n(n)` methods to emit real‑time best bid/ask and top‑5 (or configurable depth) snapshots to eqats’ signal‑generation pipelines.
- Benchmarks show ~50 ns per BBO query and ~118 ns per top‑5 query on 300 k events, suitable for high‑frequency strategies.

### 3. Historical Data Playback & Validation
- Leverage the provided CSV benchmark data (`norm_book_data_300k.csv`) to replay historical Level 2 streams for strategy back‑testing.
- The warm‑up/verification approach (first 200 k events for correctness, last 100 k for performance) can be adopted in eqats’ CI to ensure any changes to the order‑book logic preserve BBO and depth accuracy.

### 4. Language Bindings
- Use the existing Python package (`pip install ninjabook`) for rapid prototyping or integration with eqats’ Python‑based analytics.
- For latency‑critical paths, call the Rust core directly via PyO3 or Rust FFI, keeping the same API surface.

## Signal & Execution Logic Domain
ninjabook does not contain signal generation, strategy logic, or order‑execution components. Therefore, no direct integration points exist in this domain. eqats should continue to house its own signal/strategy modules, consuming the market‑data feeds provided by ninjabook.

## Risk Engineering Domain
Similarly, ninjabook lacks risk‑limit checks, position sizing, or risk‑monitoring features. Risk‑engineering responsibilities remain within eqats’ existing risk‑management subsystem, which can ingest the order‑book state from ninjabook to compute real‑time risk metrics (e.g., market‑impact estimates, liquidity‑adjusted VaR).

## Implementation Steps
1. **Add Dependency** – Include `ninjabook` crate (Rust) or PyPI package (Python) in eqats’ project.
2. **Wrap Orderbook** – Create a thin adapter in eqats that implements the eqats market‑data interface, delegating updates to ninjabook and exposing BBO/top‑N via eqats’ event bus.
3. **Benchmark Integration** – Run eqats’ existing latency benchmarks with ninjabook enabled; compare against current implementation to verify performance gains.
4. **Testing** – Use the supplied CSV data to run regression tests ensuring BBO and depth outputs match expectations.
5. **Documentation** – Update eqats’ architecture docs to reflect ninjabook as the primary Level 2 engine, noting its MIT license and performance characteristics.

## Conclusion
By adopting ninjabook as the core Level 2 order‑book engine, eqats gains a battle‑tested, low‑latency market‑data component that can significantly reduce ingestion overhead while maintaining correctness. The integration is confined to the Data Engines domain; signal/execution and risk layers remain unchanged, consuming the enriched market data that ninjabook provides.
