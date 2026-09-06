# Integration Blueprint for nse-screener into eqats

## Overview
The nse-screener repository provides a web-based interface for screening National Stock Exchange (NSE) stocks using HTML, CSS, and JavaScript. Its core value lies in the data fetching pipeline and the screening logic that applies user-defined filters to generate actionable stock lists.

## Domain Mapping
- **Data Engines**: The repository fetches real-time NSE equity data via public APIs, normalizes JSON responses, and caches them for quick reuse.
- **Signal & Execution Logic**: Screening criteria (price thresholds, volume spikes, moving averages, RSI, etc.) are implemented as JavaScript functions that produce boolean signals for each stock.
- **Risk Engineering**: Simple risk metrics such as daily volatility, average true range, and max drawdown are computed for each filtered stock to aid position sizing.

## Integration Plan
Because the original codebase is frontend‑centric and tightly coupled to the browser DOM, the reusable logic resides in isolated JavaScript modules (e.g., dataFetcher.js, screenerEngine.js). We will port these modules to Rust, exposing them through PyO3 bindings so they can be invoked from the eqats Python layer or directly from the Rust core.

### Steps
1. Extract the pure functions from dataFetcher.js and screenerEngine.js into Rust equivalents.
2. Replace browser‑specific fetch calls with reqwest HTTP client, adding async support.
3. Implement caching using an in‑memory LRU map (or once_cell sync lazy) to mimic the original sessionStorage behavior.
4. Translate technical indicator calculations (SMA, EMA, RSI) using the ta crate or custom implementations.
5. Expose a screen_stocks(filters: Json) -> Result<Vec<StockSignal>, Err> function via PyO3.
6. Add unit tests that compare outputs against the original JavaScript test fixtures (if available).
7. Integrate the resulting Rust library into eqats’ data engine pipeline, allowing the risk engine to consume the screened symbols for further analysis.

## Expected Outcome
A Rust/Python native component that replicates the nse-screener’s screening capability, enabling eqats to ingest live NSE data, apply customizable filters, and produce risk‑adjusted signals without relying on a web UI.