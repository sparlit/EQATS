# Integration Blueprint: StockMart → eqats

## Overview
StockMart provides a production-ready multiplayer trading platform built with Rust (backend) and React/TypeScript (frontend). Its core strengths-real-time WebSocket market data, order book/portfolio storage, instant trade execution, admin-driven market controls, circuit breakers, and configurable starting capital-map directly onto the three eqats domains.

## Data Engines
- **Real-time market data ingestion**: StockMart pushes live quotes, trade ticks, and order-book updates over WebSocket (see "Real-time Everything" and "WebSocket" badge). eqats can subscribe to these WebSocket streams as an external market-data feed, normalizing them into its internal tick format.
- **Order book & portfolio storage**: The platform maintains a persistent order book per symbol and tracks each player's portfolio (cash + positions). eqats can reuse this storage layer (or adapt its schema) to hold the canonical limit-order book and account-level balances for strategy back-testing and live simulation.
- **Live leaderboard & configurable company roster**: Leaderboard updates are derived from portfolio values; the company roster can be customized via the admin dashboard. eqats can ingest the leaderboard stream as a performance signal and treat the company list as a tradable-instrument catalog.

## Signal & Execution Logic
- **Instant trade execution**: Trades are matched and confirmed immediately upon receipt (see "Real-time Everything"). eqats can route its generated signals to StockMart's matching engine via the same WebSocket API, achieving low-latency execution in the simulated environment.
- **Admin-controlled market hours**: Organizers can open/close the market at will (see "Market Hours Control"). eqats can synchronize its strategy clock to these market-state signals, enabling precise in-sample/out-of-sample windows for event-based strategies.
- **Circuit breakers**: Automatic halts when prices move too fast (see "Circuit Breakers"). eqats can treat a circuit-breaker event as a risk signal to suspend strategy execution or flatten positions.
- **Custom companies & flexible timing**: Users can define fictional stocks or adjust round length (see "Custom Companies" and "Flexible Timing"). eqats can dynamically load new instrument definitions and adjust simulation horizons without code changes.
- **One-click game reset & player initialization**: Administrators can reset all accounts to a defined starting capital (see "One-Click Game Reset"). eqats can use this feature to reset the simulation state between Monte-Carlo runs or across different strategy evaluations.

## Risk Engineering
- **Price-movement circuit breakers**: Already described; they act as a hard risk limit on adverse price swings. eqats can monitor the circuit-breaker flag and automatically reduce leverage or exit positions.
- **Configurable starting capital**: By setting the initial cash per player, eqats can enforce position-sizing rules relative to a known capital base (e.g., max 10% of equity per trade).
- **Player moderation (ban/mute)**: While primarily a social control, it can be repurposed as a risk-management knob to exclude malfunctioning agents or abusive strategies from the simulation.
- **Real-time monitoring**: Live charts and admin dashboard give visibility into P&L, exposure, and order flow, enabling eqats to build real-time risk dashboards that ingest the same WebSocket feeds.

## Implementation Steps
1. **WebSocket connector** – Build a thin adapter in eqats that subscribes to StockMart's market-data WebSocket, normalizes ticks, and publishes to eqats' internal data bus.
2. **Order-execution gateway** – Implement an execution handler that sends limit/market orders via StockMart's trading API (presumed to be the same WebSocket channel) and receives fills.
3. **State synchronization** – Periodically pull portfolio and leaderboard snapshots via REST/WebSocket to keep eqats' risk engine in sync with the simulated accounts.
4. **Circuit-breaker handler** – Listen for market-halt events and trigger eqats' risk-limit logic (e.g., cancel open orders, flatten positions).
5. **Configuration module** – Expose admin-dashboard-style controls (starting capital, market open/close, company list) as eqats configuration parameters, allowing non-programmers to set up simulations.
6. **Testing harness** – Leverage StockMart's extensive test suite (463 backend, 136 E2E) to validate the integration layer.

## Benefits
- **Zero-risk, realistic simulation** – Uses the same engine that powers live competitions, ensuring fidelity.
- **Rapid setup** – No need to build a matching engine; reuse StockMart's proven Rust/Tokio backend.
- **Educational alignment** – Directly supports the use cases outlined for colleges and event organizers.
- **Extensible** – Custom companies and flexible timing let eqats experiment with arbitrary asset universes and event-driven strategies.
- **Compliant** – Self-hosted nature keeps all data within the organization's network, satisfying institutional policies.
