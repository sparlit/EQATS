# Integration Blueprint: Polymarket Trading Bot Rust → eqats

## Overview
The Polymarket‑Trading‑Bot‑Rust repository provides a mature Rust‑based trading framework that interacts with Polymarket’s CLOB via a native SDK. Its core strengths lie in:
- **Robust market data ingestion** (SDK‑driven HTTP/WebSocket polling).
- **Flexible strategy execution** (dual‑limit, trailing stop, BTC‑specific variants) with live/simulation/backtest modes.
- **Config‑driven risk controls** (asset enable flags, hedge timing, dual‑limit sizing).
- **Utility binaries** for balance, allowance, order validation, and order lifecycle operations.

These features can be mapped onto the three eqats domains and incorporated to extend eqats’ capabilities for prediction‑market or CLOB‑based trading.

---

## 1. Data Engines

### Current Features
- **CLOB SDK integration** – loads `libclob_sdk*.so` at runtime via `libloading` to fetch order books, trade history, and market metadata over HTTP/WebSocket.
- **History file replay** – `.toml` files under `history/` enable deterministic backtesting of strategies.
- **Simulation/paper mode** – bypasses real order placement while still consuming live market data.
- **Config & secret handling** – `config.json` (non‑secret) + `.env` (private keys, API credentials) loaded at startup.
- **Docker support** – ensures glibc version matches the bundled SDK, simplifying deployment.

### How to Integrate into eqats
1. **Market Data Adapter** – wrap the existing CLOB SDK calls into an eqats‑compatible `MarketDataFeed` trait. Provide implementations for:
   - Real‑time order book & ticker streaming (WebSocket).
   - Historical snapshot loading from `.toml` files.
2. **Unified Config Loader** – extend eqats’ configuration system to read a JSON file similar to `config.json` and overlay environment variables (e.g., `POLYMARKET_PRIVATE_KEY`).
3. **Simulation Layer** – reuse the bot’s `--simulation` flag concept to gate order submission in eqats’ execution engine, allowing strategy validation without affecting live positions.
4. **Container‑Ready Deployment** – adopt the provided Dockerfile as a base for eqats services that require a specific glibc/SDK version, ensuring reproducibility across environments.

---

## 2. Signal & Execution Logic

### Current Features
- **Dual‑limit entry** – places paired buy/sell limit orders at configurable offsets; variants include same‑size, BTC‑specific 5‑minute intervals.
- **Trailing‑stop strategy** – dynamically adjusts stop price based on market movement.
- **Live / simulation toggles** – `--simulation`, `--no-simulation`, `--backtest`, `--history-file`.
- **Order utilities** – `test_limit_order`, `test_sell`, `test_merge`, `test_redeem`, `test_allowance` for validating and executing order lifecycle operations.
- **Multi‑order checks** – batch validation of allowance, limits, and balances before submission.
- **CLI‑driven binaries** – each strategy/util is a separate binary (`main_dual_limit_*`, `main_trailing`, `backtest`, etc.) sharing a common core.

### How to Integrate into eqats
1. **Strategy Plugin System** – expose each strategy (dual‑limit, trailing stop, BTC‑5‑min) as an eqats `Strategy` trait implementation. Parameters (price offset, size, hedge timing) are read from the strategy section of `config.json`.
2. **Execution Modes** – map the bot’s flags to eqats execution contexts:
   - `--simulation` → `ExecutionMode::Simulation` (orders logged, not sent).
   - `--no-simulation` → `ExecutionMode::Live`.
   - `--backtest` + `--history-file` → `ExecutionMode::Backtest` using a historical feed.
3. **Order Execution Wrapper** – reuse the bot’s order placement logic (via the CLOB SDK) inside eqats’ `OrderExecutor`. The utility binaries provide reference implementations for limit, market, merge, and redeem orders that can be called directly or adapted.
4. **Pre‑trade Validation** – incorporate the `test_*` binaries’ checks (allowance, balance, limits) as eqats pre‑trade risk guards, executed automatically before any order is submitted.
5. **Binary Consolidation** – instead of maintaining separate binaries, expose a single eqats binary with subcommands (`eqats strategy dual-limit`, `eqats strategy trailing`, `eqats utils allowance`, etc.) mirroring the original Cargo `[[bin]]` layout.

---

## 3. Risk Engineering

### Current Features
- **Asset enable flags** (`enable_*_trading`) in `config.json` to turn on/off BTC, ETH, SOL, XRP markets.
- **Hedge timing & dual‑limit sizing** – configurable price offsets, order sizes, and timing between legs to manage exposure.
- **Allowance & balance validation** – `test_allowance`, `test_balance` binaries ensure sufficient USDC and token approvals before trading.
- **Proxy wallet handling** – supports EOA, proxy, and Safe‑style signature types via `POLYMARKET_SIGNATURE_TYPE` and `POLYMARKET_PROXY_WALLET_ADDRESS`.
- **API key nonce** – optional `POLYMARKET_API_KEY_NONCE` to prevent replay attacks and rate‑limit issues.
- **Docker isolation** – guarantees glibc/SDK compatibility, reducing runtime‑environment risk.

### How to Integrate into eqats
1. **Feature‑Flag Mapping** – translate `enable_*_trading` into eqats’ market‑whitelist mechanism, allowing dynamic activation/deactivation of prediction‑market instruments.
2. **Position Sizing Module** – adopt the dual‑limit price/shares logic as a template for eqats’ `PositionSizer`; expose parameters (offset, size, hedge delay) in the strategy config.
3. **Pre‑Trade Risk Checks** – integrate the allowance/balance validation flow into eqats’ risk engine, running them as synchronous guards before order submission.
4. **Signature & Wallet Abstraction** – encapsulate the proxy wallet logic into eqats’ `WalletProvider` interface, supporting EOA, proxy, and Safe signatures with configurable `signature_type`.
5. **Nonce Management** – provide an optional nonce field in eqats’ API credential store, mirroring `POLYMARKET_API_KEY_NONCE` for derived key stability.
6. **Containerized Runtime** – reuse the Dockerfile (or derive from it) to build eqats images that guarantee the correct glibc version for any native SDKs eqats may depend on.

---

## Conclusion
By incorporating the Polymarket Trading Bot Rust’s market data adapter, strategy plugins, execution modes, and risk‑control utilities, eqats can rapidly gain:
- **Production‑grade CLOB connectivity** for Polymarket and similar venues.
- **Plug‑and‑play strategy library** (dual‑limit, trailing stop, BTC‑specific) with live/simulation/backtest support.
- **Config‑driven risk limits** and pre‑trade validation that reduce operational exposure.
- **Docker‑friendly, reproducible deployments** that align native SDK binaries with the host environment.

The integration path is straightforward: wrap the existing Rust components as eqats services/traits, reuse the configuration and environment‑variable patterns, and expose the functionality through eqats’ unified CLI and API. This will extend eqats’ capabilities into the prediction‑market/CLOB niche while leveraging a battle‑tested, open‑source foundation.
