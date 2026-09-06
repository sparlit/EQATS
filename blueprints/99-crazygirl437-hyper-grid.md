# Integration Blueprint: Grid Trading Features from hyper-grid into eqats

## Overview
The `hyper-grid` repository provides a mature, feature‑rich implementation of a perpetual‑futures grid trader built with Rust/Tauri. Its core concepts—real‑time market data ingestion, ATR‑driven dynamic grids, refill‑on‑fill execution, and multi‑layer risk controls—can be extracted and adapted as a plug‑in module for the eqats quantitative trading framework.

## 1. Data Engines
- **WebSocket Market Data Feed**: Reuse the Hyperliquid WebSocket connector to stream best‑bid/ask and last‑price ticks. eqats can wrap this in its existing `MarketDataAdapter` interface, providing a unified ticker stream for any strategy.
- **ATR Indicator**: Implement an ATR calculator (configurable candle interval, period, and multiplier) that consumes historical OHLCV data from the same feed. The output (half‑width %) drives dynamic grid bounds, mirroring hyper‑grid’s `ATR_INTERVAL`, `ATR_PERIOD`, and `ATR_MULTIPLIER` settings.
- **Configuration Persistence**: Store API keys and strategy parameters in an encrypted local file (eqats’ existing `ConfigStore` can be extended). This mirrors hyper‑grid’s `.env` approach while keeping secrets off‑disk.
- **Mode Selector**: Add a runtime flag for `Simulation`, `Testnet`, or `Mainnet` that switches the endpoint and optionally loads faucet‑funded test balances, just as hyper‑grid does via its UI.

## 2. Signal & Execution Logic
- **Grid Specification**: Allow users to define a grid by either explicit lower/upper prices or by a percentage band around the live mid (`RANGE_PCT`). The module calculates level prices based on the chosen spacing (arithmetic or geometric).
- **Order Placement Engine**: On initialization, place limit buys below the mid and limit sells above. When a fill occurs, the engine automatically places the opposite order at the next grid level (refill‑on‑fill), exactly as described in hyper‑grid’s step 3.
- **Dynamic vs Fixed Grid**: Implement a toggle: *Fixed* uses static bounds; *Dynamic* recenters the band using the ATR‑derived half‑width, with optional soft recentering that retains the current position (hyper‑grid’s default).
- **Breakout Handling**: Introduce configurable breakout‑confirm bars (`CONFIRM_BARS`). After the required number of closed candles outside the band, trigger one of several actions: pause, cancel‑stop, or recenter (with cooldown and daily limits).
- **Execution Controls**: Provide `Pause`, `Resume`, and `Stop` commands. `Stop` cancels all open orders and issues a market‑order flatten for the symbol, matching hyper‑grid’s safety behavior.
- **Preview & Validation**: Before starting, run a dry‑run that checks sufficient notional per level, leverage limits, and margin mode compatibility, preventing invalid starts.

## 3. Risk Engineering
- **Drawdown & Daily Loss Limits**: Integrate circuit‑breaker logic that monitors equity curve; if either max drawdown or daily loss threshold is breached, automatically issue a `Stop` (cancel + flatten).
- **Order‑Failure Guard**: Track consecutive order‑submission failures; halt the strategy after `MAX_ORDER_FAILURES` attempts, requiring manual reset.
- **Leverage & Margin Mode**: Expose leverage and margin‑mode (cross/isolated) as strategy parameters, validating against exchange limits.
- **Position Sizing**: Compute order size as `total_notional / grid_levels`, ensuring each level respects the exchange’s minimum order size.
- **Session Persistence**: On shutdown, persist open orders and position state; on restart, attempt to resume (`RESUME_ON_RESTART`) or auto‑start (`AUTO_START`) if no resumable session exists, mirroring hyper‑grid’s close‑window policies.

## 4. Integration Steps
1. **Create a new eqats strategy package** `eqats-strategy-grid`.
2. **Implement the MarketDataAdapter** for Hyperliquid WebSocket, reusing hyper‑grid’s connection logic.
3. **Build the ATRIndicator** service, exposing configurable interval, period, and multiplier.
4. **Develop the GridEngine** core: grid spec generation, order placement, refill‑on‑fill, dynamic recentering, breakout logic, and execution controls.
5. **Add RiskModule** with drawdown, daily loss, and failure‑counter guards.
6. **Expose a configuration UI** (or JSON/YAML) that maps directly to hyper‑grid’s settings: `RANGE_PCT`, `GRID_LEVELS`, `TOTAL_NOTIONAL`, `SPACING`, `LEVERAGE`, `MARGIN_MODE`, `GRID_MODE`, `ATR_*`, `CONFIRM_BARS`, `RECENTER_COOLDOWN`, `MAX_DRAWDOWN`, `DAILY_LOSS`, `MAX_ORDER_FAILURES`, `AUTO_START`, `RESUME_ON_RESTART`, `EXIT_POLICY`.
7. **Write unit tests** using historical Hyperliquid data to validate grid behavior, refill logic, and risk triggers.
8. **Document** the strategy in eqats’ strategy catalog, highlighting the simulation/testnet/mainnet modes and the safety‑first approach.

By directly porting these well‑tested features, eqats gains a robust, production‑ready grid‑trading capability that inherits hyper‑grid’s proven risk controls and execution discipline while benefiting from eqats’ broader analytics, orchestration, and multi‑asset framework.
