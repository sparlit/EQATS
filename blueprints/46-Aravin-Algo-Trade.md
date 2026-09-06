# Integration Blueprint for eqats

## Overview
The Algo-Trade repo provides a browser-based "Nifty" weekly options bot. Its architecture splits into a React dashboard, Cloudflare Worker proxy, D1 persistence, and Fastify backend. The most valuable pieces for eqats are the data ingestion, five-layer scoring engine, and risk controls.

### 1. Data Engines
- Market Data Ingestion: reuse the "Upstox" API wrapper (fetchMarket, fetchMarketSentiment) to get 1‑min candles, option chain, FII/DII, VIX, and place/exit orders. Add a "MoneyControl" client for global index technical ratings.
- Proxy Layer: if running in-browser, keep a lightweight Worker‑style CORS proxy; otherwise call APIs directly from eqat's backend.
- Persistence: replace localStorage with a D1‑style SQLite (or eqat's "Postgres") store for broker accounts, strategy config, and runtime state. Provide migration scripts similar to `wrangler d1 migrations apply`.
- Scheduler: a 60‑second polling loop that updates market data, computes scores, and persists snapshots.

### 2. Signal & Execution Logic
- Five‑Layer Scoring: port scoreBullish() and scoreBearish() functions. Layers: L0 VIX hard stop, L1 macro ("MoneyControl" + breadth), L2 technicals (EMA 10/42, ADX, RSI, Stochastic, Bollinger Bands, ATR), L3 institutional (synthetic MMI, FII long/short, net positioning, straddle IV vs VIX), L4 confluence gate (min score gap & absolute threshold).
- State Machine: IDLE → RUNNING → ORDERED → RUNNING/STOPPED, ticking every 60 s.
- Automated Exit: trigger on target P/L (absolute or trailing), indicator/macro reversal, or index breadth flip.
- Strategy Config UI: mirror the React panels (MarketSetup, Institutional, Breadth, Indicators, Score, BotControls, StrategyConfig) to expose confidence thresholds, profit/loss limits, max trades per day, last entry time, strike offset.
- Order Execution: use "Upstox" order endpoints via eqat's broker adapter.

### 3. Risk Engineering
- Hard Stops: block trading when VIX < 10 or > 25; synthetic "Nifty" PE adds a small penalty.
- Dynamic Limits: configurable confidence thresholds, profit/loss limits, max trades per day, last entry time (default 14:30 IST), strike offset (OTM skip).
- Monitoring: expose state machine step, latest scores, and P/L via eqat's health endpoint; log risk events.

### 4. Deployment
- If eqat's is server-based, omit the Worker layer and call APIs directly with secrets managed by eqat's.
- For browser use, expose a Fastify/Express middleware that proxies "Upstox"/"MoneyControl" with CORS.
- Persistence: map D1 tables to eqat's "Postgres" (broker_accounts, strategy_configs, runtime_state, market_snapshots) and provide migration scripts.
- Testing: adapt the existing "Vitest" suite for unit tests of scoring and state machine.

## Summary
Integrating these components gives eqat's a ready‑made, rule‑based options trading pipeline with robust data flow, transparent scoring, and layered risk controls, easily adaptable to other indices or asset classes.
