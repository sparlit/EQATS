# Integration Blueprint: AlgoMLN → eqats

## Overview
AlgoMLN is a Rust‑based, engine‑first algorithmic trading platform that cleanly separates data ingestion, indicator computation, strategy execution, and broker interaction. Its modular design, deterministic backtesting, and plugin architecture make it a strong candidate for enriching the eqats stack.

## Proposed Mapping to eqats Domains

### 1. Data Engines
- **Broker Abstraction & DhanClient**: Adopt the `BrokerClient` trait as a template for eqats’ broker interface, allowing plug‑and‑play implementations for Dhan, Alpaca, Interactive Brokers, etc.
- **Data Models**: Reuse or adapt the `Candle`, `Tick`, `Quote`, `Order`, `Position` structs (with Serde support) to standardize internal data contracts.
- **WebSocket Manager**: Integrate the high‑concurrency WS manager (auto‑reconnect, 1k symbol limit) into eqats’ market‑data feed layer.
- **Tick‑to‑Candle Aggregator**: Plug the per‑symbol 1‑minute candle builder into eqats’ real‑time pipeline to derive OHLCV from raw ticks.
- **Historical OHLCV Fetch**: Use the existing fetch logic as a reference for eqats’ historical data loader.
- **Tauri IPC (optional)**: If eqats adopts a Tauri‑based desktop UI, the IPC commands can be mirrored to expose live data to the frontend.

### 2. Signal & Execution Logic
- **Indicator Library**: Import the pure‑Rust indicator functions (MA, EMA, RSI, ATR, VWAP, relative volume, Bollinger Bands) directly into eqats’ signal‑generation module. Their stateless signature `fn(&[Candle], usize) -> Vec<f64>` fits a functional pipeline.
- **DSL & Compiler Pipeline**: Evaluate embedding AlgoMLN’s `.algomln` language as an optional strategy authoring format in eqats. The lexer/parser/AST/validator/runtime can be wrapped as a reusable crate; eqats would provide its own broker‑agnostic `ExecutionTarget` implementations.
- **Trigger State & Cross Detection**: Re‑use the trigger‑state system (fires on false→true) and cross helpers to simplify eqats’ rule‑engine.
- **PaperBroker**: Adopt the `PaperBroker` logic (cash, positions, avg entry, realized PnL) as eqats’ default simulation backend, ensuring deterministic backtests.
- **ExecutionTarget Trait**: Align eqats’ broker abstraction with this trait so the same strategy engine can drive paper, sandbox, and live execution.
- **Deterministic Backtest & CLI**: Incorporate the candle‑by‑candle replay and `behavioral_backtest` binary as eqats’ backtesting CLI, guaranteeing same‑input/same‑output runs.
- **Plugin System**: Leverage the capability‑gated plugin framework (Rhai + WASM) to let eqats users extend indicators, analytics, DSL keywords, storage, UI panels, schedulers, and order‑gateway logic without touching core code.

### 3. Risk Engineering
- **Current Gap**: AlgoMLN does not yet implement explicit risk limits, position sizing, or real‑time risk monitoring. The DSL only parses (does not evaluate) `position_expr` and `time_window`, hinting at planned risk‑related constructs.
- **Integration Idea**: Use the plugin capability system as a foundation for risk‑engine plugins. eqats could define a `RiskManagement` capability that plugins must declare to access position sizing, stop‑loss, max‑drawdown, or margin checks. The existing gating mechanism would then enforce that only authorized plugins can invoke risk‑affecting calls.
- **Future Work**: Implement the missing `position_expr` and `time_window` evaluators to enable rule‑based position sizing and time‑of‑day filters directly in the DSL, then expose them through the plugin‑gated risk interface.

## Implementation Steps
1. **Create a `datamodels` crate** in eqats based on AlgoMLN’s structs, adding Serde derives.
2. **Extract the `BrokerClient` trait and DhanClient** into a `broker` crate; adapt to eqats’ async execution model.
3. **Port the WebSocket manager and tick‑to‑candle aggregator** into eqats’ market‑data layer, preserving auto‑reconnect and fan‑out semantics.
4. **Vendor the indicator library** as a `signals` crate; expose each indicator as a pure function.
5. **Wrap the DSL compiler pipeline** (lexer → parser → AST → validator → runtime) into a `strategy_dsl` crate, providing an API that accepts a `.algomln` string and returns an executable strategy object.
6. **Implement the PaperBroker** as eqats’ default `ExecutionTarget` for backtesting and simulation.
7. **Expose the deterministic backtest runner** (`behavioral_backtest`) as a CLI subcommand in eqats.
8. **Integrate the plugin system**: reuse the Rhai and WASM sandboxes, define capability IDs matching eqats’ needs (e.g., `RiskManagement`, `OrderGateway`), and enforce permission checks at call‑site.
9. **Document the extension pathway** for quant developers: how to write a plugin that registers a new indicator, adds a DSL keyword, or injects risk logic.
10. **Add tests**: AlgoMLN’s 341 passing workspace tests provide a solid baseline; replicate critical data‑flow and strategy‑execution tests in eqats to ensure correctness.

## Expected Benefits
- **Rapid strategy prototyping** via a simple, readable DSL.
- **High‑performance backtesting** (≈50k candles/sec on modest hardware) thanks to O(N) indicator windows and deterministic replay.
- **Zero‑cloud, local‑first operation** aligning with eqats’ desire for offline‑capable quant workflows.
- **Extensible, secure plugin ecosystem** allowing community‑built indicators, risk models, and UI panels without compromising core stability.
- **Unified execution path** for paper, sandbox, and live trading, reducing integration complexity.

By adopting these concrete components, eqats can accelerate its feature roadmap while benefiting from a battle‑tested, deterministic engine and a clean separation of concerns across data, signal, and risk layers.