# Integration Blueprint for eqats

## Overview
Option Workstation provides a rich set of features for options research, volatility analytics, dealer exposure analysis and guarded paper trading. The most valuable capabilities can be mapped onto the three eqats domains—Data Engines, Signal & Execution Logic, and Risk Engineering—to enhance eqats with robust market‑data handling, strategy construction and risk monitoring.

## Data Engines
- **Historical Replay** – Leverage the existing ThetaData Parquet partition reader to provide point‑in‑time snapshots of underlying prices, option chains and OI. eqats can reuse this loader to feed historical data into its back‑testing engine while guaranteeing no look‑ahead bias.
- **Real‑Time Feed** – Integrate the Longbridge Rust SDK (already used in the workstation) to stream live quotes and depth.Expose freshness metrics (quote age, bid/ask spread, OI coverage) as first‑class fields that eqats can gate downstream calculations on.
- **Unified Calculation Service** – Pull the Rust‑based modules that compute BSM IV/Greeks, SVI fits, volatility surfaces, GEX/Vanna/Charm and dealer‑exposure metrics into a shared library (e.g., a `eqats‑analytics` crate). This ensures consistency between historical and live modes.
- **Snapshot & Audit Ledger** – Adopt the append‑only JSONL hash‑chained ledger for storing research snapshots (underlying, timestamp, expiry, layout, legs) and for immutable audit trails of strategy decisions. eqats can store these ledgers alongside its own execution logs for reproducibility.

## Signal & Execution Logic
- **Strategy Builder** – Mirror the workstation’s “mirrored options chain” UI: allow users to add Call/Put legs, adjust buy/sell direction and quantity, and select from preset strategies (straddle, strangle, vertical spreads, iron condor) or define custom multi‑leg structures.
- **Pre‑Trade Analytics** – For each leg compute executable NBBO cash flow, max profit/loss, breakeven, probability of profit (POP) and generate a spot/IV/time scenario matrix. eqats can display these metrics in real time as the user edits a strategy.
- **Paper‑Trading Gateway** – Implement a server‑side gate similar to the workstation’s simulated order flow: only limit orders are permitted, and submission is allowed only after all data‑quality checks (fresh quote, bid/ask availability, OI coverage) and risk limits pass.
- **Research Snapshots & Bookmarking** – Provide a one‑click “save snapshot” that stores the current underlying, time, expiry, layout and legs. These snapshots can be reloaded for replay or shared via the audit ledger, supporting the workflow described in the workstation’s “快照、比较与审计” section.

## Risk Engineering
- **Portfolio Risk Engine** – Use the workstation’s executable NBBO pricing to calculate portfolio P&L under spot, IV and time scenarios. eqats can surface the resulting matrix as a heat‑map or contour plot.
- **Exposure Analytics** – Integrate the GEX, Vanna, Charm, dealer‑exposure walls and gamma‑flip calculations. Display these as overlay charts on the underlying price chart, with tooltips showing the underlying assumptions (dealer short/long).
- **Volatility Analytics** – Provide ATM IV, IV rank/percentile, realized variance (RV5/10/20), VRP and expected move, mirroring the workstation’s “波动率状态” panel. Include clear disclaimers when BSM approximations are used for American options.
- **Smile/SVI Surface** – Offer call/put smile, SVI fitting, residual analysis and term‑structure views. Surface quality scores (`Trusted`/`Research`) and constraint‑check results (butterfly, price monotonicity, calendar) should be visible, and metrics should be disabled automatically when data is sparse or adjustments are large.
- **Risk Gating** – Before any order is sent to the paper‑trading gateway, evaluate a composite risk score that includes: data‑quality flags (fresh quote, OI coverage), exposure limits (max GEX, wall proximity), volatility‑risk limits (IV rank thresholds) and scenario‑based loss limits. Only when all gates pass is the order enabled.

## Implementation Steps
1. **Create a shared analytics crate** (`eqats‑analytics`) containing the Rust modules for BSM, SVI, Greeks, GEX/Vanna/Charm, surface fitting and snapshot ledger.
2. **Wrap the Longbridge SDK** in an async service that emits normalized quote events with freshness and OI‑coverage metadata.
3. **Build the strategy UI** (React/Vite) that mirrors the mirrored chain, allows leg manipulation and preset selection, and calls into the analytics crate for real‑time P&L and scenario outputs.
4. **Develop the paper‑trading gateway** with server‑side validation (limit‑order only, data‑quality checks, risk limits) and an order‑simulation logger.
5. **Integrate the audit ledger** (JSONL hash‑chained) for snapshots and order events, providing a tamper‑evident research log.
6. **Add risk‑monitoring panels** (exposure, volatility, scenario matrix) that subscribe to the analytics crate and update whenever market data or strategy changes.
7. **Provide configuration toggles** to switch between historical replay (using local ThetaData partitions) and live mode, ensuring the same code path for calculations.

By incorporating these features, eqats will gain a transparent, reproducible and risk‑aware environment for options research and simulated trading, directly reflecting the strengths of the Option Workstation while staying within the declared capabilities of the repository.
