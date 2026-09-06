# Integration Blueprint for eqats: NSE AutoResearch Features

## Overview
The autoresearch-nse repository demonstrates an autonomous research loop that iterates on trading strategies using a fixed backtest harness (prepare.py) and an editable strategy file (strategy.py). Its core concepts can be ported to the eqats project to enable continuous strategy discovery and risk-aware execution.

## Data Engines
- NSE Data Ingestion: The repo loads daily OHLCV data for a given symbol (e.g., SBIN) over a 10‑year window. eqats can adopt a similar loader for Indian equities or extend it to global markets via CCIT/yfinance.
- Backtest Engine (prepare.py): A fixed script that computes equity curve, fees, and the three‑target composite score. eqats could wrap its existing backtester in a thin, immutable harness that exposes only the metric to be minimized.
- Experiment Logging: Results are appended to results.tsv (git‑ignored) with columns for commit, score, total_return, sharpe, max_drawdown, total_trades, status, description. eqats can implement a comparable immutable log to preserve the research trail.

## Signal & Execution Logic
- Editable Strategy File: Only strategy.py is modified by the agent, encouraging rapid prototyping of signal rules (EMA crossovers, SMA filters, etc.). eqats can enforce a similar contract where the research agent edits a dedicated strategy.py while the execution layer remains untouched.
- Autonomous Loop: The agent reads program.md, hacks the strategy, commits, runs prepare.py, evaluates the composite score, and either keeps or reverts the change via Git. eqats can replicate this loop using its own GitOps pipeline, allowing 24/7 strategy evolution.
- Signal Library: The repo relies on TA‑Lib for technical indicators. eqats can integrate TA‑Lib or its own indicator suite to generate signals within the editable strategy.

## Risk Engineering
- Multi‑Objective Score: The composite score penalizes deviation from total return (≥250%), Sharpe (≥1.2), and max drawdown (≤18%). eqats can adopt a comparable weighted score that aligns with its risk‑return objectives.
- Capital & Fees: Starting capital of ₹10,00,000 and realistic transaction costs (~0.1345% per side) are modeled in the backtest. eqats can inject its own capital model and fee schedule into the fixed harness.
- Risk Limits: By enforcing a drawdown threshold in the score, the loop inherently discourages overly risky strategies. eqats can extend this with explicit risk limits (position sizing, stop‑loss) that are checked inside the immutable prepare step.

## Integration Steps for eqats
1. Define an Immutable Harness – Create prepare_eqats.py that loads market data, runs the backtest, applies fees, and returns a single scalar score (lower = better) based on eqats’ target metrics.
2. Create an Editable Strategy – Provide strategy_eqats.py where the autonomous agent can implement signal generation and position logic.
3. Set Up Git‑Driven Loop – Agent reads program_eqats.md, edits strategy_eqats.py, commits, runs the harness, evaluates the score, and either keeps (advances branch) or resets (git reset HEAD~1).
4. Log Experiments – Append each run to a TSV/CSV log with commit hash, score, and performance metrics for auditability.
5. Leverage Existing Libraries – Use TA‑Lib/pandas/numpy for indicator calculations; ensure the harness installs these via requirements.txt.

By mirroring the structure of autoresearch-nse, eqats gains a fully autonomous, Git‑backed research loop that continuously improves strategies while respecting risk constraints.