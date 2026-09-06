# Integration Blueprint for eqats: AlgoTradingNSE Features

## Overview
The AlgoTradingNSE repository demonstrates a machine‑learning‑driven momentum strategy on Indian NSE stocks. It ingests ten years of OHLCV data for five large‑cap stocks, builds technical‑indicator features, trains an ensemble of KNN, Decision Tree, Random Forest and SVM classifiers to predict the next‑day price trend, and converts the prediction into simple BUY/SELL/HOLD signals. The reported accuracy is 94.2%.

## Data Engines (Ingestion & Storage)
- **Data Source**: CSV files containing daily OHLCV for RELIANCE, HDFC, ITC, INFOSYS, TCS (10‑year history).
- **Ingestion**: pandas.read_csv loads each stock into a DataFrame; dates are parsed and set as index.
- **Feature Engineering**: Technical indicators (e.g., SMA, EMA, RSI, MACD, Bollinger Bands) are calculated using pandas/numpy and appended as columns.
- **Storage for eqats**: The cleaned feature matrix can be persisted in eqats's feature store (e.g., Parquet or Delta Lake) for offline training and online retrieval.

## Signal & Execution Logic
- **Model**: Ensemble voting classifier (scikit‑learn VotingClassifier) combining KNN, DecisionTreeClassifier, RandomForestClassifier, SVC with probability outputs.
- **Target**: Binary label – Uptrend (next day close > today close) vs Downtrend.
- **Prediction**: Probability threshold 0.5 → class label.
- **Signal Rules** (as in repo):
  - If predicted Uptrend and no existing BUY position → emit BUY signal.
  - If predicted Downtrend and no existing SELL position → emit SELL signal.
  - Otherwise → HOLD.
- **Execution**: Signals are fed to a simple back‑tester that calculates daily P&L based on next‑day open/close; equity curve and total return are computed.
- **Integration into eqats**:
  1. Replace the ad‑hoc back‑tester with eqats's execution engine (e.g., paper‑trading or live broker adapter).
  2. Expose the ensemble model as a eqats signal generator (REST/gRPC service) that consumes the latest feature vector and returns a signal enum.
  3. Use eqats's signal routing to apply the BUY/SELL/HOLD logic, allowing position‑state tracking and idempotent order submission.
  4. Leverage eqats's order‑management system to convert signals into limit/market orders with configurable slippage.

## Risk Engineering
- **Current State**: The repository does not implement explicit risk controls (position sizing, stop‑loss, max drawdown, leverage limits).
- **Suggested Additions for eqats**:
  - **Position Sizing**: Use eqats's risk module to allocate a fixed % of equity per trade (e.g., 1‑2%) or volatility‑based sizing.
  - **Stop‑Loss / Take‑Profit**: Attach OCO orders based on ATR or fixed percentage.
  - **Exposure Limits**: Enforce max long/short exposure per stock and sector via eqats's risk engine.
  - **Monitoring**: Feed real‑time P&L and drawdown metrics into eqats's risk dashboard; trigger automatic flattening if drawdown exceeds threshold.
  - **Model Risk**: Periodic retraining schedule and performance decay detection (e.g., rolling accuracy) using eqats's model‑monitoring utilities.

## Implementation Steps
1. **Data Pipeline**: Adapt the CSV‑reading code to eqats's data‑ingestion connectors (e.g., eqats.data.sources.CSVSource or a custom NSE API connector).
2. **Feature Store**: Write the engineered indicator DataFrame to eqats's feature store (Parquet) with versioning.
3. **Model Training**: Re‑use the scikit‑learn ensemble training script; register the trained model in eqats's model registry.
4. **Signal Service**: Deploy a thin wrapper that loads the model from the registry, fetches the latest feature row, predicts, and returns a signal (BUY, SELL, HOLD).
5. **Execution Hook**: Connect the signal service to eqats's strategy runner; configure the BUY/SELL/HOLD rule engine.
6. **Risk Layer**: Activate eqats's risk‑management plugins (position sizing, stop‑loss) around the strategy.
7. **Back‑test & Paper Trade**: Run eqats's back‑tester on the historical data to validate that the integrated pipeline reproduces the 94.2% accuracy and comparable returns before going live.

## Expected Benefits
- **Reusability**: Leverages eqats's robust data pipelines, feature store, and model registry.
- **Scalability**: Enables multi‑stock, multi‑timeframe expansion beyond the five NSE stocks.
- **Risk‑aware Trading**: Adds professional risk controls absent in the original notebook.
- **Production Readiness**: Moves from exploratory notebook to a deployable, monitored service.