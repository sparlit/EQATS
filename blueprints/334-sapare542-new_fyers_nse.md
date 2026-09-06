# Integration Blueprint for eqats

## Overview
The `sapare542/new_fyers_nse` repository provides a simple end‑to‑end algo‑trading pipeline that uses the Fyers broker API, technical‑indicator based signals (Supertrend + ADX), brute‑force hyper‑parameter selection, and Telegram alerts. While the code is educational, several components can be reused or adapted inside the eqats framework.

## Data Engines Integration
- **Market Data Ingestion** – Replace or augment eqats’ current data feed with a thin wrapper around the Fyers REST/WebSocket API (similar to the `fyers/` package used in the repo). This provides live tick‑by‑tick or OHLCV streams for Indian equities.
- **Historical Data Retrieval** – The brute‑force optimization loop downloads past data for each candidate stock; eqats can adopt this pattern for its own walk‑forward or parameter‑search modules.
- **Storage** – `accounts_database.py` shows how to persist live market data into a SQL database (likely using SQLAlchemy). eqats can integrate this as a optional persistence layer for audit trails, replay, or offline analysis.
- **File Formats** – The repo likely writes CSVs for intermediate results; eqats can reuse the same CSV handling for quick prototyping.

## Signal & Execution Logic Integration
- **Supertrend + ADX Strategy** – The core logic (Supertrend calculation, ADX threshold, buy/sell execution) can be packaged as a new eqats strategy class (`SupertrendADXStrategy`). eqats already supports plug‑in strategies; this would add a well‑known trend‑following system.
- **Brute‑Force Parameter Search** – The nested loops that iterate over Supertrend multiplier and period values map directly onto eqats’ optimization engine. By exposing the strategy’s parameters to eqats’ optimizer, users can automatically discover the best settings per instrument.
- **Chartink‑Based Stock Selection** – The script that pulls a list of candidates from Chartink can be turned into a eqats universe‑filter plugin, allowing dynamic re‑selection of the tradable universe before each trading session.
- **Order Execution** – The repo uses the Fyers API to place market/limit orders. eqats can adopt the same order‑submission helper (wrapping `fyers.Model.place_order`) to route signals to the broker.
- **Telegram Alerts** – A simple `telegram.Bot` push notification can be wrapped as an eqats alerting channel, providing real‑time strategy‑event notifications to traders.

## Risk Engineering Integration
- **ADX Filter as Volatility Gate** – The rule “no trade when ADX < 30” can be imported as a pre‑trade risk filter in eqats’ risk module, preventing entries in low‑volatility regimes.
- **Missing Controls** – The repo does not implement position sizing, stop‑loss, max‑drawdown, or leverage limits. When integrating the strategy, eqats should overlay its standard risk engine (e.g., volatility‑scaled position sizing, ATR‑based stops, daily loss limits) to ensure safe operation.
- **Monitoring** – The Telegram alerts can be extended to include risk metrics (current P&L, margin usage) by hooking into eqats’ risk‑monitoring hooks.

## Summary
By incorporating the Fyers data connector, the Supertrend/ADX signal logic, the brute‑force optimizer, and the Chartink universe selector into eqats, traders gain a ready‑to‑run, parameter‑searchable trend‑following system. The risk‑engineering gap can be filled by eqats’ existing risk controls, yielding a robust, production‑grade module.
