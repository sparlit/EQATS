# Integration Blueprint for kostorub/backtest into eqats

## Overview
The kostorub/backtest repository provides a Rust‑based backtesting framework with Binance historical data handling, a grid bot strategy, and a lightweight SQLite store. These components can be leveraged to enhance eqats’ data pipelines, strategy execution, and observability.

## Data Engines
- **Binance Historical Data Ingestion**: Reuse the download logic that pulls klines from Binance Data Collection and stores them as memory‑mapped files (timestamp, open, high, low, close, volume each 8 bytes). Integrate this as a plug‑in data source in eqats’ market‑data layer, enabling low‑latency replay of 1‑second and trade‑level data.
- **Chunked Iteration & Gap‑Filling**: Adopt the same‑period chunk iteration to process data in low‑memory windows, filling missing klines with the previous valid bar. This can be wrapped in eqats’ `DataEngine` trait to provide deterministic backtest slices.
- **SQLite Persistence Layer**: Use the existing SQLite schema (users, downloaded market‑data metadata, backtest parameters & metrics) as a reference for persisting eqats’ backtest runs and user configurations. The WAL mode and Docker‑K8s deployment notes give a ready‑made ops pattern.
- **Data Models & Handlers**: Migrate the `data_models` and `data_handlers` modules into eqats’ `data_engines` crate, exposing strongly‑typed Kline structs and utility functions for validation, resampling, and format conversion.

## Signal & Execution Logic
- **Grid Bot Strategy**: Import the grid‑bot implementation (based on Binance Spot Grid description) as a reference strategy. Adapt its core functions (`calculate_grid_levels`, `execute_grid_orders`) into eqats’ strategy SDK, allowing users to declare grid parameters via YAML/JSON and run them across multiple symbols using the existing multithreaded background.
- **Backtesting Engine & Metrics**: Reuse the engine that iterates over klines, computes PnL, trade counts, and other metrics. Hook its metric calculators into eqats’ `risk_engineering` module to produce standardized performance reports.
- **UI & Charting**: Although eqats may prefer a different frontend, the Pico CSS + Plotly chart generation code can be extracted as a lightweight reporting widget for internal dashboards or for exporting equity curves.
- **Multithreaded Multi‑Symbol Backtest**: Leverage the repository’s design for concurrent symbol processing to scale eqats’ batch backtesting jobs on Kubernetes pods.

## Risk Engineering
The source repository does not contain explicit risk‑limit, position‑sizing, or monitoring components. Therefore, no direct risk‑engineering features can be imported. Eqats should continue to rely on its own risk modules (VaR, max drawdown, leverage caps) and consider adding risk hooks that consume the backtest engine’s output (e.g., post‑run risk metrics).

## Integration Steps
1. **Fork & Vendor**: Add the kostorub/backtest repo as a git submodule or vendor the `src/backtest`, `src/data_handlers`, `src/data_models`, and `src/chart` directories into eqats’ `vendor/` tree.
2. **Create Adapter Layer**: Write Rust adapters that convert the vendor’s Kline struct to eqats’ `MarketDatum` type and expose a `DataEngine` trait implementation.
3. **Wrap Grid Bot**: Define a `GridBotStrategy` struct that implements eqats’ `Strategy` trait, delegating to the vendor’s core functions while receiving configuration from eqats’ config system.
4. **Reuse Metrics**: Extract metric‑calculation functions and call them from eqats’ `PerformanceAnalyzer` to populate the standard metrics JSON.
5. **Update CI/CD**: Mirror the existing Dockerfile/Kubernetes workflow (digital‑ocean.yml) to build and push the eqats‑extended image, reusing the same base image and sqlx preparation steps.
6. **Test**: Run the vendor’s test suite alongside eqats’ unit tests to ensure compatibility; add integration tests that run a grid‑bot backtest on a sample Binance dataset and verify the produced metrics.
6. **Document**: Add a section to eqats’ docs referencing the borrowed grid‑bot and data‑engine components, with links to the original Binance guides.

By following this blueprint, eqats gains a high‑performance, low‑memory market‑data engine and a proven grid‑bot strategy, while maintaining its own risk‑engineering and extensibility goals.
