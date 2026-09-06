# Integration Blueprint

## Overview
Integrate the backtesting engine from AlgoTrade-API into eqats as a Rust core module exposed via PyO3.

## Components
- **Data Engines**: Reuse historical data fetching; eqats already has market data engine; we add a lightweight CSV/Parquet loader.
- **Signal & Execution Logic**: The backtester will consume signal series and simulate execution.
- **Risk Engineering**: Incorporate position sizing and risk metrics into the backtest.

## Implementation Steps
1. Add PyO3 dependency to eqats Cargo.toml.
2. Create eqats/src/backtest.rs with a run_backtest function.
3. Expose via eqats/src/lib.rs using pyo3::wrap_pyfunction!.
4. Write unit tests in Rust and a Python pytest.

## Data Flow
Historical prices -> signal series -> backtester -> performance metrics (returns, Sharpe, max drawdown).

## Risks
- Ensure data alignment; handle missing values.
- Kotak API specifics remain in execution layer; backtester is broker-agnostic.
