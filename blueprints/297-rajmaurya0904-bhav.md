# Integration Blueprint for eqats from bhav

## Overview
The bhav repository provides a mature options backtesting engine tailored for the Indian NSE market. Its core strengths lie in deterministic Parquet outputs, realistic cost modeling, and a pluggable data layer that can ingest Upstox historical data (including expired contracts). These features map cleanly onto the three eqats domains.

## Data Engines
- Parquet cache & deterministic output – Every 1‑minute candle is fetched once from Upstox and stored locally as Parquet; subsequent runs reuse the cache, guaranteeing reproducible results. eqats can adopt a similar immutable artifact store for market data, enabling version‑controlled backtests.
- Expired‑instrument fetching – bhav pulls expired option chains via Upstox’s `expired-instruments` endpoint, allowing backtests on delisted contracts. eqats could expose a generic “historical‑instrument” adapter that wraps any broker’s expired‑data API.
- Warm‑up & lot‑size tables – Automatic warm‑up days and per‑underlying lot‑size/ATM‑step lookup ensure strategies start with correct history and correct contract multipliers. eqats can integrate a lookup service that feeds lot size and step size into the signal engine.
- Futures‑basis ATM selection – The `--atm-reference futures` flag rolls the front‑month future automatically, removing spot‑future basis bias. eqats could add a configurable ATM reference (spot vs futures) with auto‑roll logic.
- Multi‑leg & offline dataset – Support for CE/PE combinations and a bundled sample dataset enables strategy development without a live account. eqats could ship a lightweight sample data bundle for quick iteration.

## Signal & Execution Logic
- Lifecycle‑hook strategy API – `on_bar`, `on_day_start`, `on_day_end`, etc., let users write plain Python strategies that receive deterministic context objects. eqats can adopt a similar hook‑based API, making strategy porting straightforward.
- Partial/tranche closes – `ctx.close(key, lots=N)` enables scaling out of a position slice. eqats could expose a `reduce_position` method with identical semantics.
- AI‑generated strategies – The `bhav generate` command uses a locally installed Claude CLI to turn English into a strategy file, guarded by an AST validator that blocks unsafe imports. eqats could integrate a similar “generate‑from‑prompt” pipeline, reusing its own safety gate.
- Static safety gate – AST validation rejects `os`, `subprocess`, `eval`, `open`, network imports before execution. eqats should adopt a comparable static analysis step for any user‑submitted or AI‑generated code.
- Monte Carlo robustness – Each run bootstraps the trade sequence 1 000× to produce return/drawdown bands, probability of profit, and risk of ruin. eqats can plug this Monte Carlo post‑processor into its risk engine.
- Multi‑leg support – Vertical spreads, iron condors, ratios, and straddles are natively handled. eqats’ signal engine should allow multi‑leg order construction from a single signal.

## Risk Engineering
- Realistic Indian cost model – Includes STT (sell + exercised ITM), brokerage, exchange transaction charges, SEBI charges, stamp duty, GST. eqats can replace its generic cost model with this India‑specific version when trading NSE instruments.
- Drawdown & P&L analytics – The built‑in dashboard shows equity curve, drawdown, P&L distribution, and full trade log. eqats can reuse these visualisation components (or adapt the underlying metrics) for its own reporting.
- Risk‑of‑ruin & probability of profit – Derived from Monte Carlo bands, these metrics give a quantitative view of strategy robustness. eqats should surface similar summary statistics in its risk reports.
- Margin/SPAN placeholder – Not yet implemented in bhav, but the roadmap notes it as future work. eqats could contribute a SPAN‑margin module that plugs into the existing cost‑model framework.

## Integration Steps for eqats
1. Data layer – Wrap the Upstox client (or a generic historical‑instrument interface) to cache candles as Parquet and implement warm‑up lot‑size lookup.
2. Strategy API – Define a base `Strategy` class with `on_bar`, `on_day_start`, `on_day_end`, and `on_trade` methods; expose a `Context` object providing `close(key, lots=N)` and position‑tracking helpers.
3. Safety gate – Add an AST‑based validator that runs before any strategy execution, mirroring bhav’s `bhav/ai/validate.py`.
4. Cost model – Replace eqats’ generic fee calculator with the Indian cost model from bhav, parameterised by instrument type.
5. Risk engine – Integrate the Monte Carlo bootstrap utility to produce return/drawdown bands, probability of profit, and risk of ruin; expose these via the existing risk‑reporting API.
6. UI/Reporting – Optionally adopt the FastAPI + Next.js dashboard (or reuse its charting components) to visualise eqats backtests.
7. AI strategy generation – Hook a local LLM (Claude or similar) into a `generate` command that outputs a strategy file, then run it through the safety gate before execution.

By incorporating these features, eqats will gain a robust, production‑grade backtesting pipeline for Indian options, with deterministic outputs, realistic costs, AI‑assisted strategy creation, and comprehensive risk analytics.