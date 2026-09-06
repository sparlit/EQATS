# Integration Blueprint for eqats

## Overview
The ai-algotrading-agent repository provides a TypeScript‑based algorithmic trading toolkit that mirrors the original Python eqats core. Its clean separation of concerns makes it a valuable source for enhancing eqats in three domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

## Data Engines
- **CSV Market Data Loader** – `src/data/csv.ts` exports `loadMarketFromFile` and `listMarketsOnDisk`. These functions read `"hist-{interval}/*.csv"` files and return typed `MarketRow[]` arrays. eqats can reuse this loader (or adapt it to Python/pandas) to support its existing CSV‑based historic data format without adding new dependencies.
- **Optional Redis Cache** – The `src/cache/` folder shows how to wrap backtest results with an ioredis client keyed by a hash of the request parameters. Integrating a similar cache layer in eqats would speed up repeated backtests and reduce recomputation.
- **Tick‑by‑Tick Replay** – `src/engine/tickByTick.ts` implements a deterministic replay loop that emits candles with a configurable delay. This can be wrapped as a simulation mode in eqats for strategy validation at higher fidelity than bar‑based backtests.

## Signal & Execution Logic
- **Indicator Library** – `src/indicators/` contains SMA and Bollinger Band implementations that operate on plain arrays (no pandas). Porting these pure‑functions to eqats would allow strategy developers to reuse the same logic across Python and TypeScript stacks.
- **Strategy Functions** – Entry and exit factories (`src/strategies/entry.ts`, `exit.ts`) expose higher‑order functions like `crossSmas(smaFast, smaSlow)` returning `(market: MarketRow[]) => boolean`. eqats can adopt this pattern to keep strategy definitions decoupled from the engine.
- **Signal Engine** – `src/engine/signals.ts` combines indicators, strategies, and risk checks to produce `isTimeToBuy` and `isTimeToExit`. Replicating this orchestrator in eqats would centralize decision‑making and simplify adding new signal sources.
- **Execution Engines** – The backtest (`src/engine/backtest.ts`) and tick‑by‑tick engines drive the simulation loop, handle order filling, commission deduction, and P&L aggregation. eqats could import the core loop logic (after translating to Python) or expose a thin wrapper that calls the TypeScript build via a subprocess for heterogeneous testing.
- **CLI & Programmatic API** – `src/cli.ts` parses commands like `backtest`, `tick`, and `realtime`. The public API exported from `src/index.ts` shows how eqats could offer a similar `eqats.backtest({markets, entryFns, exitFns, ...})` interface.

## Risk Engineering
- **Stop‑Loss & Trailing Stop** – `src/risk/stops.ts` provides `stopLoss(entryPrice, pct)` and `trailingStopLoss(peakPrice, pct)`. These functions are invoked by the signal engine based on the `STOP_TYPE` env variable (0 = off, 1 = fixed, 2 = trailing, 3 = both). eqats can adopt the same parameterization to unify risk configuration across backtest, simulation, and live modes.
- **Commission Modeling** – A simple flag (`COMMISSION_ENABLED`) multiplies trade quantity by a fixed commission (e.g., BNB commission). Integrating this into eqats’ order executor would ensure that performance metrics reflect realistic costs.
- **Environment‑Driven Configuration** – The `src/config/vars.ts` file reads `".env"` variables and supplies typed defaults. eqats could mirror this approach to keep risk parameters externalizable without code changes.

## Integration Steps
1. **Data Layer** – Add a TypeScript‑to‑Python bridge (or directly port `csv.ts`) to eqats’ data ingestion module, preserving the `"hist-{interval}/*.csv"` folder structure.
2. **Indicator & Strategy Port** – Copy the pure‑function implementations from `src/indicators/` and `src/strategies/` into eqats’ strategy library, exposing them as callable entries.
3. **Signal Orchestrator** – Implement an `eqats.signals` module that mirrors `src/engine/signals.ts`, plugging in the imported indicators, strategies, and risk checks.
4. **Engine Wrapper** – Create a thin eqats wrapper around the backtest/tick‑by‑tick loops (or translate the loops to Python) that accepts the same configuration object shown in the example programmatic usage.
5. **Risk Module** – Introduce `eqats.risk.stopLoss` and `eqats.risk.trailingStopLoss` functions, and expose a `RiskConfig` object populated from environment variables or a config file, similar to `src/config/vars.ts`.
6. **Caching (Optional)** – If eqats would benefit from rapid backtest iteration, add a Redis‑backed cache layer following the pattern in `src/cache/`.
7. **Testing** – Use the existing Vitest suite as a reference for unit‑testing the ported functions; eqats can adopt similar test structures to ensure parity with the original Python implementation.

By following this blueprint, eqats gains a well‑typed, modular TypeScript reference implementation that can be used for cross‑language validation, rapid prototyping, and eventual migration of performance‑critical components to Node.js if desired.