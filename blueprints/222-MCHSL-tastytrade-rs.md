# Integration Blueprint for tastytrade-rs into eqats

## Overview
The `tastytrade-rs` library provides a Rust client for the tastytrade API, enabling authentication, account data retrieval, and order construction with dry-run risk assessment.

## Data Engines Integration
- **Account & Position Data**: Use `TastyTrade::login` and `account().await` to fetch balances, positions, and live orders. These can feed eqats' market data engine to maintain real‑time portfolio state.
- **Market Data Feed**: The live orders endpoint provides streaming‑like updates; eqats can poll or subscribe to keep the order book and execution state current.

## Signal & Execution Logic Integration
- **Order Building**: Reuse `OrderLegBuilder` and `OrderBuilder` to translate eqats-generated signals (e.g., target symbols, quantities, sides) into tastytrade order objects.
- **Dry‑Run Validation**: Before submission, invoke `account.dry_run(&order).await` to obtain a simulated execution report, allowing eqats to verify feasibility, slippage, and fees without risking capital.
- **Order Submission**: Extend the dry‑run flow with a real `account.place_order(&order).await` call (available in the library) to execute validated signals.

## Risk Engineering Integration
- **Risk Metrics Extraction**: The dry‑run result includes `BuyingPowerEffect` (margin change, buying power impact) and `FeeCalculation`. eqats can map these to its risk limits (e.g., max margin usage, max fee budget) and reject orders that exceed thresholds.
- **Pre‑Trade Checks**: Incorporate the buying‑power effect and fee impact into eqats' pre‑trade risk engine to enforce position‑size limits and margin constraints.
- **Post‑Trade Monitoring**: Use retrieved account balances and positions after execution to update eqats' risk dashboard and trigger alerts if limits are breached.

## Implementation Steps
1. Add `tastytrade-rs` as a dependency in eqats' Rust crate.
2. Create a thin adapter module exposing:
   - `login(credentials) -> TastyTrade`
   - `fetch_account_data() -> (Balance, Positions, LiveOrders)`
   - `build_order(signal) -> Order`
   - `validate_order(order) -> DryRunResult`
   - `submit_order(order) -> OrderResult`
3. Wire the adapter into eqats' data pipeline (market data engine) and execution engine.
4. Configure risk limits in eqats to consume the `BuyingPowerEffect` and `FeeCalculation` fields from dry‑run results.
5. Test with paper‑trading mode (`false` flag in login) before enabling live trading.

## Considerations
- The library is marked as work‑in‑progress; verify API coverage for needed endpoints (e.g., option chains, market data).
- Async runtime compatibility: ensure eqats' tokio/async‑std setup matches the library's expectations.
- Error handling: propagate `Result` types to allow eqats to retry or log failures.
