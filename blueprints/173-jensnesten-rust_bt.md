# Integration Blueprint for rust_bt into eqats

## Overview
rust_bt provides a high-performance backtesting and live trading engine written in Rust, with modular components for data handling, strategy execution, and risk management. The following outlines how its notable features can be incorporated into the eqats project.

## Data Engines
- **OHLC CSV Ingestion**: The `handle_ohlc` function loads historical OHLC data from CSV files (e.g., `data/SP500_DJIA_2m_clean.csv`). This can replace or supplement eqats' current data loader.
- **Live Data Streaming**: The `rust_live` crate offers an interface to connect to real‑time market data APIs, enabling eqats to stream live bid/ask prices.
- **Market Microstructure Simulation**: Built‑in modeling of bid‑ask spread, slippage, commissions, and margin requirements allows realistic transaction cost analysis during backtests and live runs.
- **Data Structures**: Core types such as `OhlcData`, `LiveData`, `Broker`, and `LiveBroker` are already defined in `rust_core` and can be reused via FFI or as a Rust dependency.

## Signal & Execution Logic
- **Strategy Trait**: Strategies implement the `Strategy` trait (or `LiveStrategy` for live mode). eqats can define its own strategies by implementing this trait, gaining access to the engine’s order‑book logic and position management.
- **Order Types & Execution**: Supports market, limit, contingent (stop‑loss/take‑profit), fractional, and scaled orders. The engine handles order submission, filling, and statistics updates.
- **Multiple Instruments & Pairs Trading**: The engine natively supports trading multiple symbols and pairs strategies, which aligns with eqats’ multi‑asset focus.
- **Plotting & Statistics**: Automatic generation of equity curves, Sharpe ratio, drawdown, win‑rate, etc., can be hooked into eqats’ monitoring dashboard.
- **Example Integration**: In `rust_bt/src/main.rs` the engine is instantiated with a `Backtest` object; eqats could replicate this pattern, injecting its own data feed and strategy implementation.

## Risk Engineering
- **Margin & Leverage Management**: Parameters `margin` (leverage factor) and `max margin usage` reporting allow eqats to enforce leverage limits and monitor margin consumption.
- **Position Sizing & Fractional Orders**: The `scaling_enabled` flag and fractional order support enable dynamic position sizing based on risk signals.
- **Risk Controls**: Contingent orders (SL/TP) provide automated loss‑limiting and profit‑taking mechanisms.
- **Exclusive Orders & Hedging**: Flags `exclusive_orders` and `hedging` let eqats model mutually exclusive positions or hedge strategies.
- **Performance Metrics**: The engine reports key risk‑adjusted metrics (Sharpe, alpha, beta, volatility) directly after each run, facilitating real‑time risk dashboards.

## Implementation Steps
1. Add `rust_bt` as a dependency (git submodule or crate) to the eqats Rust workspace.
2. Expose the `handle_ohlc` function (or create a wrapper) to load eqats’ historical data.
3. For live trading, instantiate a `LiveBroker` from `rust_live` and connect it to eqats’ data subscription layer.
4. Implement eqats’ trading logic as a struct that implements the `Strategy` trait (or `LiveStrategy`), placing orders via the provided `Broker` API.
5. Configure risk parameters (`cash`, `commission`, `bidask_spread`, `margin`, `trade_on_close`, `hedging`, `exclusive_orders`, `scaling_enabled`) according to eqats’ risk policy.
6. Run the backtest via `Backtest::new(...).run()` or launch live mode via `rust_live::main`.
7. Consume the engine’s output statistics (equity curve, Sharpe, drawdown, etc.) to feed eqats’ risk monitoring and reporting systems.

## Considerations
- The engine is deliberately barebones; eqats may need to extend it with additional asset‑class specifics (e.g., futures, options) or more sophisticated order‑book models.
- Integration via FFI or as a native Rust dependency will give eqats access to the engine’s low‑latency performance benefits.
- Ensure that any custom data formats are converted to the OHLC struct expected by `handle_ohlc` before ingestion.