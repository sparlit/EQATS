# Integration Blueprint for eqats from Paul-Folbrecht/algo-trading

## Overview
The algo-trading repository provides a Rust‑based framework for algorithmic trading that includes market data ingestion, persistence, a simple mean‑reversion strategy, and a backtesting harness. The following blueprint maps its notable components to the three eqats domains and outlines concrete steps for integration.

## 1. Data Engines
- **MongoDB Storage** – The repo uses MongoDB to persist `positions`, `orders`, and `pnl` collections. eqats can adopt the same pattern by defining MongoDB schemas for these entities and reusing the existing connection logic (environment variable `MONGO_URL`).
- **Tradier Market Data Ingestion** – Access to real‑time and historical data is obtained via the Tradier API using `ACCESS_TOKEN`/`SANDBOX_TOKEN`. eqats can wrap the existing HTTP client (likely `reqwest` + `serde`) to fetch quotes, bars, and account data, feeding them into the signal layer.
- **Configurable Data Ranges** – Parameters `hist_data_range` (look‑back for indicator calculation) and `backtest_range` (days of historical data for backtesting) are set in `default.toml`. eqats should expose analogous configuration keys so that strategies can request the required window size.
- **Backtesting Engine** – The `backtest` binary replays historical data, computes the Bollinger Bands signal, and records resulting P&L and open positions in MongoDB. eqats can reuse this backtest harness by plugging in its own strategy interface.

## 2. Signal & Execution Logic
- **Mean‑Reversion (Bollinger Bands) Strategy** – Defined in `[[strategies]]` with name `mean-reversion`, a list of `symbols`, and per‑symbol `capital`. The strategy logic (presumably in the source) calculates upper/lower bands and generates buy/sell signals when price crosses the bands.
- **Symbol & Capital Configuration** – Each strategy can trade multiple symbols with independent capital allocations, enabling simple position sizing.
- **Order Execution** – Live trading is launched via `cargo run --bin server` (or `./scripts/run.sh`). The server reads the access token from the environment and submits orders through the Tradier API. eqats can invoke the same execution endpoint or adapt the client to its own execution abstraction.
- **Backtest Binary** – Running `cargo run --bin backtest` produces realized P&L and open positions, providing a fast feedback loop for strategy validation.

## 3. Risk Engineering
- **Capital Allocation per Strategy** – The `capital` array in the TOML assigns a dollar amount to each symbol, acting as a rudimentary risk limit (max capital exposed). eqats can extend this with per‑strategy max‑loss, volatility‑scaled sizing, or stop‑loss rules.
- **Sandbox Mode** – Setting `sandbox = true` and providing a `sandbox_token` lets users test orders without risking real capital—a useful risk‑mitigation feature for development.
- **Secret Management** – Following the 12‑factor approach, sensitive values (`ACCESS_TOKEN`, `SANDBOX_TOKEN`, `ACCOUNT_ID`, `MONGO_URL`) are supplied via environment variables, reducing the chance of credential leakage.
- **Missing Features** – The repository does not include explicit risk‑engineering components such as max position size, drawdown limits, real‑time risk monitoring, or liquidity checks. These would need to be added in eqats.

## 4. Integration Steps
1. **Data Layer**
   - Add a MongoDB module mirroring the `positions`, `orders`, and `pnl` collections.
   - Create a Tradier client wrapper that reads `TRADIER_ACCESS_TOKEN`/`TRADIER_SANDBOX_TOKEN` and provides market data functions (quotes, historical bars).
   - Expose `hist_data_range` and `backtest_range` as global config parameters.
2. **Strategy Layer**
   - Implement the Bollinger Bands indicator as a reusable Rust library.
   - Define a strategy trait (`SignalGenerator`) that the mean‑reversion strategy implements.
   - Allow multiple symbols per strategy with configurable capital (risk‑scaled position size).
3. **Execution Layer**
   - Reuse the existing order‑submission client or adapt it to eqats’ execution interface.
   - Provide a `server` binary that reads strategies from config, subscribes to market data, generates signals, and sends orders.
   - Keep the `backtest` binary for offline validation.
4. **Risk Layer**
   - Start with the capital‑allocation approach; then layer additional risk rules (max notional, stop‑loss, volatility targeting).
   - Ensure all secrets remain environment‑driven.
5. **DevOps**
   - Follow the provided Docker build instructions (`rustup target add x86_64-unknown-linux-gnu; docker build --platform=linux/amd64 -t eqats .`).
   - Use the `scripts/run.sh` and `scripts/backtest.sh` as templates for eqats’ own scripts.

## 5. Caveats
- The original project is marked as *personal* and *not for production use*; thorough testing and additional risk controls are required before deploying in eqats.
- Only a single strategy is demonstrated; extending to multiple strategies will require the strategy registry and conflict‑resolution logic.
- No explicit logging or observability is mentioned; eqats should add structured logging and metrics.
