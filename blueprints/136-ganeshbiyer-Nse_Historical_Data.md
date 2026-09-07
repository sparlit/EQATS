# Integration Blueprint for Nse_Historical_Data in eqats

## Overview
The ganeshbiyer/Nse_Historical_Data repository provides minute-level historical OHLCV data for the Nifty 500 universe and key indices (Nifty, BankNifty, FinNifty, MidcapNifty) stored as yearly partitioned Parquet files up to 31 Dec 2025.

## Data Engine Integration
1. Ingestion – Use pandas.read_parquet or pyarrow.parquet.read_table to load any year-wise file into a DataFrame.
2. Storage – Mirror the yearly partitioning inside eqats's data lake (e.g., data/raw/nse_minute/{year}/{symbol}.parquet).
3. Catalog – Register each Parquet file in eqats's metadata store (e.g., AWS Glue or Delta Lake) with columns: timestamp, open, high, low, close, volume.
4. Versioning – Since the repo plans to move future years to separate repos, eqats can treat each year-wise repo as a data version and automate pulls via GitHub Actions.

## Signal & Execution Logic
*No direct signal or execution code is present in the repository. However, the clean minute-bar dataset can be fed into eqats's strategy engine for:*
- Backtesting intraday strategies (e.g., VWAP, momentum, mean-reversion).
- Generating features for machine-learning models (e.g., lagged returns, volume-weighted price).
- Simulating order execution using eqats's execution adapter with realistic slippage models.

## Risk Engineering
*The repository does not contain risk-related logic. The data can be used for:*
- Calculating intraday volatility, value-at-risk (VaR), and drawdown metrics.
- Feeding risk-monitoring dashboards that track exposure per symbol or sector.
- Supporting stress-testing scenarios by replaying historical minute bars under eqats's risk engine.

## Implementation Steps
1. Add a new data-source connector in eqats/connectors/nse_minute.py that wraps pandas.read_parquet.
2. Schedule a nightly GitHub Actions workflow to clone the relevant year-wise repo and sync Parquet files to eqats's S3 bucket.
3. Update the eqats data catalog to point to the new location.
4. Create a sample backtest notebook demonstrating the use of Nifty 500 minute data for an intraday mean-reversion strategy.
5. Document the data schema and update eqats's data-dictionary.

## Benefits
- Immediate access to high-quality, survivorship-bias-free minute data for Indian equities.
- Enables eqats to expand its backtesting horizon to 2018-2025 without building custom scrapers.
- Facilitates research on index-arbitrage and sector-rotation strategies using the provided index files.

## Limitations
- Data ends at 31 Dec 2025; future years must be pulled from the planned yearly repos.
- No corporate-action adjustments (splits, dividends) are applied; eqats may need to adjust bars if required.
