# Integration Blueprint for eqats

## Overview
The Ronak‑59/Stock‑Prediction repository provides a JavaScript‑based prototype that combines mutual fund analysis, news sentiment, time‑series forecasting (Stateful LSTM), and portfolio risk metrics. While the original project was built for a hackathon, its core components can be refactored and wrapped as reusable services for the eqats quantitative trading platform.

## 1. Data Engines

### 1.1 Market Data Ingestion
- **Dow Jones Top 30 Stocks** – historic price series can be pulled via eqats’ market data adapter (e.g., Polygon, Alpaca) and stored in the same format used by the repo (CSV/JSON).
- **Mutual Funds Holdings** – eqats can ingest mutual fund NAV and holdings data from providers (Morningstar, SEC filings) and expose it as a `mutual_funds` table.
- **News Sentiment** – eqats already has a news pipeline; the repo’s sentiment analysis can be replaced by eqats’ NLP service (e.g., VADER, FinBERT) to produce a sentiment score per ticker.

### 1.2 Storage & Feature Store
- Raw price series → `ohlcv` table.
- Mutual fund exposure → `fund_holdings` table.
- Sentiment scores → `news_sentiment` table.
- Engineered features (LSTM inputs, risk factors) → eqats feature store for offline training and online inference.

### 1.3 Exploratory & Histogram Analysis
- The repo’s exploratory scripts (EDA, histograms) can be converted into eqats notebooks or data‑quality checks that run nightly to validate data distributions.

## 2. Signal & Execution Logic

### 2.1 Stateful LSTM Predictor
- The LSTM implementation (likely TensorFlow.js) can be ported to Python/TensorFlow or PyTorch and wrapped as an eqats `ModelService`.
- Input window: past 60 days of OHLCV + sentiment + mutual‑fund exposure.
- Output: multi‑step forecast (e.g., next 5 days) → transformed into a directional signal (buy/sell/hold).

### 2.2 Prediction Analysis Module
- Generates trading signals based on forecast error thresholds and confidence intervals.
- Can be integrated into eqats’ `SignalGenerator` where each model contributes a weighted vote.

### 2.3 Algo Comparison & Selling Profit Ratio
- The repo visualises algorithm performance; eqats can adopt the same metrics (Sharpe, win‑rate, avg profit) to compare the LSTM signal against existing strategies.
- The selling profit ratio can be used as a dynamic position‑sizing factor: higher expected profit → larger allocation.

### 2.4 Order Execution
- Signals are fed to eqats’ execution engine (e.g., IBKR, Alpaca) with standard order types (market, limit).
- The repo’s “selling profit ratio” can be added as a pre‑trade filter to avoid low‑expectancy trades.

## 3. Risk Engineering

### 3.1 Portfolio Risk Factor
- The repo computes a risk factor (likely volatility or VaR) based on historical returns and mutual‑fund concentration.
- This can be mapped to eqats’ risk model: compute portfolio‑level volatility, factor exposures, and concentration limits.

### 3.2 Risk Monitoring
- Sentiment‑adjusted exposure: if news sentiment turns negative, reduce position size proportionally.
- Use the repo’s risk factor as an additional scalar in eqats’ risk‑budget allocation algorithm.

### 3.3 Limits & Controls
- Implement max‑position limits derived from the mutual‑fund analysis (e.g., no more than X% of portfolio in any single fund).
- Daily VaR limits based on the LSTM forecast distribution.

## 4. Integration Steps

1. **Data Pipeline** – Adapt eqats ingestors to pull the same datasets (DJ30, mutual funds, news) and store them in the eqats data lake.
2. **Feature Engineering** – Replicate the repo’s feature construction (lagged returns, sentiment scores, fund exposure) as eqats feature recipes.
3. **Model Service** – Export the LSTM model from TensorFlow.js to a Python SavedModel, register it in eqats Model Registry, and create a prediction endpoint.
4. **Signal Generation** – Build a new SignalGenerator plugin that consumes the LSTM forecast, applies confidence thresholds, and outputs eqats signal objects.
5. **Risk Layer** – Plug the repo’s risk factor computation into eqats risk engine as a custom risk factor.
6. **Back‑testing & Comparison** – Run the new signal through eqats’ back‑testing framework, compare against existing algorithms using the repo’s visualisation scripts (algo.png, algo2.png).
7. **Deployment** – Deploy the service behind eqats’ API gateway, enable paper‑trading, then live trading with appropriate risk limits.

## 5. Expected Benefits
- Adds a deep‑learning time‑series predictor that captures non‑linear patterns in DJ30 stocks.
- Enriches signals with mutual‑fund and sentiment fundamentals, improving robustness.
- Provides an additional risk metric (portfolio risk factor) that can be used for dynamic position sizing.
- Offers a clear visual comparison framework to evaluate the new strategy against legacy eqats algorithms.

---
*This blueprint assumes the repository’s LSTM is built with TensorFlow.js; if another library is used, adjust the model conversion step accordingly.*