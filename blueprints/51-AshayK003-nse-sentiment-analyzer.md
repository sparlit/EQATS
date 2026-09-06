# Integration Blueprint for eqats

## Overview
The NSE Sentiment Analyzer provides a rich set of data ingestion, signal generation, and risk monitoring capabilities that can be leveraged within the eqats quantitative trading platform.

## Data Engines Integration
- Smart Ticker Search: Implement a cached lookup service that maps company names/aliases to NSE tickers using Yahoo Finance REST API and yfinance, with fallback probes and handling of rebrands/splits.
- Live Market Data Feed: Pull real‑time price, change %, volume, PE, D/E via Yahoo Finance and store in eqats' market‑data engine (e.g., TimescaleDB or kdb+).
- Multi‑Source News Pipeline: Ingest RSS feeds from Moneycontrol, Economic Times, LiveMint, NDTV Profit, Google News, plus DuckDuckGo fallback; parse headlines and timestamps.
- Event‑Aware Headline Classification: Apply the 19‑event taxonomy (earnings, order wins, litigation, regulatory approvals, buybacks, etc.) with signed bias to produce event‑adjusted sentiment scores.
- SmartScore Computation: Calculate the recency‑weighted EWMA (36 h half‑life) composite (0‑100) that blends event‑adjusted sentiment, headline breadth, and news volume; store as a derived signal.
- Self‑Calibrating Source Weights: Maintain per‑source Beta‑Binomial weights updated from user feedback (👍/👎) to reflect actual predictive accuracy.
- Enhanced VADER + Indian Lexicon: Augment the sentiment engine with the 123‑term Indian financial dictionary (NPA, GNPA, NIM, tezi, mandi, etc.) and optionally switch to FinBERT.
- Technical Indicator Engine: Compute RSI(14), SMA crossovers (50/200), MACD from 2‑year OHLCV history and persist as time‑series features.
- Portfolio Holdings Store: Keep track of user holdings (quantity, average cost) and auto‑fetch LTPs for P&L calculation.
- FII/DII Flow Ingestion: Pull official NSE FII/FPI and DII net values daily and maintain a rolling 7‑day history for regime detection.
- VWAP & Pivot Levels: Calculate intraday VWAP and classic pivot (HLC‑based) support/resistance levels for intraday strategies.
- Cascade/Ripple Mapping: Use the hand‑curated commodity‑ticker relationship map (8 commodities, 27 tickers) to propagate commodity‑news sentiment to affected securities, with direction inferred from article keywords.

## Signal & Execution Logic Integration
- SmartScore as Alpha Signal: Treat the normalized SmartScore (0‑100) as a factor score; combine with traditional fundamentals/technicals in eqats' alpha model.
- Event‑Adjusted Sentiment: Feed event‑specific sentiment scores (e.g., earnings‑positive, litigation‑negative) into strategy rules or as filters.
- Technical Indicator Signals: Generate entry/exit rules from SMA crossovers, RSI thresholds, MACD histograms, and Bollinger Band breaks.
- Sentiment‑Weighted Position Sizing: Adjust position size based on source‑weighted confidence (Bayesian weights) and SmartScore magnitude.
- Cascade‑Driven Tactical Tilt: When commodity news triggers a bullish/bearish label for a ticker via the ripple map, generate a short‑term tilt signal for the affected securities.
- Portfolio‑Mode Execution: Use the holdings tracker to automate order submission (market/limit) for rebalancing based on signal changes, with integrated P&L monitoring.

## Risk Engineering Integration
- Exposure Monitoring: Use FII/DII flow trends as a macro‑risk gauge; increase risk‑aversion when net DII outflow persists.
- Liquidity & Volatility Checks: Incorporate VWAP and pivot levels to enforce intraday stop‑loss or take‑profit limits around fair value.
- Concentration Limits: Apply portfolio‑mode quantity checks to enforce max position size per ticker.
- Event‑Risk Flags: Flag holdings when negative‑bias events (litigation, regulatory penalties) are detected, triggering pre‑trade risk checks.
- Commodity‑Risk Propagation: Via cascade mapping, adjust sector‑level risk limits when commodity‑driven sentiment shifts (e.g., crude‑oil rise increases ONGC exposure but reduces OMCs).
- SmartScore‑Based VaR: Model the distribution of SmartScore changes to estimate short‑term drawdown risk and adjust portfolio leverage accordingly.
- Sentiment Confidence Intervals: Leverage the Bayesian source‑weight posterior to compute credible intervals for sentiment‑derived signals and size positions inversely to uncertainty.

## Implementation Steps
1. Data Layer – Add a new nse_sentiment connector that implements the ticker search, market‑data pull, RSS ingestion, event classification, and SmartScore calculation.
2. Feature Store – Persist raw and derived fields (price, volume, technical indicators, sentiment scores, FII/DII flow, VWAP/pivots, cascade flags) in eqats' feature store.
3. Signal Engine – Register SmartScore, event‑sentiment, and technical‑indicator features as alpha factors; define combination logic in the strategy DSL.
4. Execution Adapter – Extend the order‑generation module to consume portfolio‑mode holdings and emit rebalancing orders when signal thresholds cross.
5. Risk Module – Hook FII/DII flow, VWAP/pivots, event flags, and cascade‑derived exposures into the real‑time risk monitor; configure limits and alerts.
6. Feedback Loop – Store user 𑑍/𑑎 feedback (if eqats has a UI) to continuously update source‑weight posteriors.

## Expected Benefits
- Enhanced alpha generation from alternative‑data sentiment tailored to Indian equities.
- More nuanced risk awareness through institutional flow and commodity‑ripple effects.
- Adaptive weighting of news sources based on realized performance, reducing model decay.
- Unified pipeline for live price, fundamentals, technicals, and news—all within a single, cache‑efficient service.