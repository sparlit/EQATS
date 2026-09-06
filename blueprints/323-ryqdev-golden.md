# Integration Blueprint for `golden` into eqats

## Overview
`golden` is a Rust‑based all‑in‑one trading engine that provides CSV data ingestion from Yahoo Finance, local file loading, backtesting, paper‑trading and live‑trading with Interactive Brokers (IBKR). It also includes basic candlestick and line chart visualization.

## Data Engines
- **Yahoo Finance CSV download** – `golden csv --symbol <ticker>` pulls historical data into the `data/` directory.
- **Local CSV loader** – The engine can read CSV files directly from disk for backtesting.
- **Single data feed support** – Currently handles one symbol at a time; multiple feeds are planned.

**Integration idea for eqats:**
Wrap the CSV download and loader as reusable Rust crates (or expose via FFI) so eqats can fetch market data via the same Yahoo Finance endpoint or ingest user‑supplied CSVs. The single‑feed abstraction can be extended to eqats’ multi‑feed data engine by wrapping each symbol in a feed object.

## Signal & Execution Logic
- **Strategy framework** – A simple strategy can be written and run via `golden backtest` (uses `config.toml`).
- **Paper & live trading** – `golden paper --broker ibkr` connects to IBKR TWS for simulated or real orders.
- **Order execution** – Orders are sent through the IBKR broker integration.
- **Visualization** – Candlestick and line charts are rendered; future work includes order lists and side panels.

**Integration idea for eqats:**
Adopt the strategy trait/pipeline from `golden` as a starting point for eqats’ Signal & Execution Logic layer. The IBKR broker wrapper can be reused (or adapted) to provide eqats with a paper‑trading and live‑trading gateway. The existing charting code can be lifted into eqats’ UI module to give immediate visual feedback on signals and equity curves.

## Risk Engineering
`golden` currently lacks explicit risk‑management features (risk limits, position sizing, online monitoring). The roadmap notes a “Risk module” and “Online monitor module” as future work.

**Integration idea for eqats:**
Since `golden` does not provide reusable risk components, eqats should bring its own risk‑engineering suite (e.g., VaR limits, volatility‑based sizing, real‑time risk dashboard) and plug it into the execution flow after order generation but before submission to the broker.

## Implementation Steps
1. **Data layer** – Extract the Yahoo‑Finance CSV downloader and CSV loader from `golden` into a crate `eqats-data-ingest`.
2. **Broker layer** – Port the IBKR client used by `golden` to eqats, exposing `place_order`, `cancel_order`, and `account_summary` functions.
3. **Strategy layer** – Define a `Strategy` trait similar to `golden`’s and provide a default `SimpleMA` example that mirrors the backtest demo.
4. **Visualization** – Reuse the candlestick and line chart modules to render strategy output in eqats’ dashboard.
5. **Risk layer** – Implement eqats’ risk‑engineering middleware (position sizing, max‑drawdown checks) that sits between strategy signals and broker calls.
6. **Configuration** – Keep the TOML config format; extend it with eqats‑specific sections for risk parameters and multi‑feed definitions.

## Conclusion
While `golden` offers a solid foundation for data ingestion, strategy backtesting, and IBKR‑based execution, its risk‑management capabilities are still missing. By extracting and adapting its data and broker components, eqats can accelerate development of a private, high‑performance trading platform while adding its own advanced risk‑engineering layer on top.
