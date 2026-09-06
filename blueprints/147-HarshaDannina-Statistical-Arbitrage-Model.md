# Integration Blueprint for Statistical-Arbitrage-Model into eqats

## Overview
The repository provides a simple statistical arbitrage pipeline: extracting NSE stock data, splitting into train/test, fitting a TheilSenRegressor to predict future prices, and identifying periods where predicted vs actual divergence signals a trading opportunity.

## Data Engines Integration
- **Data Ingestion**: Replace the custom `20Micron.py` extraction script with eqats' universal data loader to pull NSE equity CSVs (or directly from a broker/API). The loader should store raw OHLCV data in eqats' time-series database (e.g., TimescaleDB) under a `nse_equity` namespace.
- **Storage & Versioning**: Use eqats' data versioning to tag the 2016 training set and 2017 test set, enabling reproducible back‑tests.
- **Feature Engineering**: The repo currently uses raw price series; eqats can augment with returns, volatility, and sector‑level correlation features via its feature store.

## Signal & Execution Logic Integration
- **Model**: Plug the TheilSenRegressor (from scikit‑learn) into eqats' signal factory as a `PricePredictionSignal`. The signal consumes the latest look‑back window (e.g., 60 days) and outputs a forecast for the next period.
- **Signal Generation**: Compute the residual `actual - predicted`. When the residual exceeds a statistically‑derived threshold (e.g., 2σ of historical residuals), emit a long/short signal assuming mean‑reversion.
- **Execution**: Connect the signal to eqats' execution adapter to generate market‑on‑close orders for the target stock, with optional scaling based on signal strength.

## Risk Engineering Integration
- The original notebook does not contain explicit risk controls. When integrating into eqats, wrap the signal with eqats' risk layer:
  - **Position Sizing**: Use volatility‑adjusted Kelly or fixed fractional sizing from eqats' risk engine.
  - **Risk Limits**: Enforce max daily loss, max gross exposure, and sector concentration limits.
  - **Monitoring**: Feed residuals and P&L into eqats' monitoring dashboard for real‑time anomaly detection.

## Implementation Steps
1. Add a new strategy module `eqats/strategies/stat_arb_theilsen.py` that loads data via `eqats.data.load_nse_equity`, splits by year, fits TheilSenRegressor, and registers a signal function.
2. Register the signal in eqats' signal registry under `stat_arb_theilsen_residual`.
3. Configure a risk profile (e.g., `stat_arb_risk.yaml`) with position sizing rules and limits.
4. Back‑test using eqats' back‑testing framework on the 2016/2017 data to verify the reported 98.2% prediction accuracy translates into a Sharpe‑ratio > 1 after costs.
5. Deploy to paper‑trading mode, monitor residuals, and adjust thresholds.

## Expected Benefits
- Leverages eqats' robust data infrastructure for scalable, multi‑symbol statistical arbitrage.
- Adds a mean‑reversion signal based on robust regression, complementing existing momentum or machine‑learning strategies.
- Gains automated risk controls, position sizing, and performance analytics absent in the original repo.