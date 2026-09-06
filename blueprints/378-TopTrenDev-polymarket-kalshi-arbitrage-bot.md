# Integration Blueprint for Polymarket-Kalshi Arbitrage Bot into eqats

## Overview
Integrate the cross‑platform arbitrage detection and execution logic from the Polymarket‑Kalshi bot into the eqats quantitative trading system. The eqats core (Rust) will expose a PyO3‑wrapped signal engine that consumes normalized market data from both platforms and emits executable trade intents.

## Components
1. **Data Engine Layer** – Reuse existing eqats connectors; add thin adapters for Polymarket (via ethers‑rs) and Kalshi (REST) that feed into a shared MarketSnapshot struct.
2. **Signal & Execution Logic** – Implement ArbitrageDetector (event matching + price discrepancy) and GabagoolExecutor as pure Rust functions returning Signal enum (Buy, Sell, Hold). The TradeExecutor translates signals into platform‑specific order requests via eqats’ execution interface.
3. **Risk Engineering Layer** – Wrap the bot’s position tracker and settlement checker inside eqats’ risk manager; enforce max‑position, dry‑run, and logging via eqats’ audit trail.

## Interaction Flow
- Market data adapters → MarketSnapshot → ArbitrageDetector → Signal → Risk checks → TradeExecutor → Platform adapters → Order submission.
- Gabagool strategy runs in parallel on Polymarket snapshots.
- Monitoring logger writes 15‑minute slot logs to eqats’ logging subsystem.

## Configuration
- Reuse .env variables; map to eqats config struct.
- Feature flags: ENABLE_CROSS_ARBITRAGE, ENABLE_GABAGOOL, DRY_RUN.

## Testing
- Unit tests for detector using mock snapshots.
- Integration test harness with simulated Polygon and Kalshi testnet endpoints.
