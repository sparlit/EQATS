# Integration Blueprint for NSEDownload into eqats

## Overview
The NSEDownload library provides a simple interface to retrieve publicly available data from the National Stock Exchange of India (NSE), including stock quotes, historical data, and index information. It returns data as pandas DataFrames, making it a convenient data source for eqats’ data engine layer.

## Data Engines Integration
- Use `getDataFromNSE` to fetch historical stock data as a pandas DataFrame.
- Retrieve index data (e.g., NIFTY 50, NIFTY AUTO) with optional start and end dates.
- Obtain Total Return Index (TRI) data by setting `indexType="TRI"`.
- The library already parses dates into the DataFrame index, aligning with eqats’ timestamp handling.

## Signal & Execution Logic Integration
- The `calculateReturnsForStocks` and `calculateReturns` functions compute trailing returns from 1 day up to 2 years, which can serve as basic signal inputs or features for strategy development.
- Outputs can be saved to Excel or CSV and fed into eqats’ signal generation pipeline.
- These return calculations can be used as baseline features (e.g., momentum) within eqats’ signal & execution logic.

## Risk Engineering Integration
- The repository does not contain explicit risk limits, position sizing, or monitoring tools.
- Risk engineering in eqats would need to be built separately, using the data fetched from NSEDownload as input.

## Implementation Steps
1. Add the library as a dependency: `pip install -i https://test.pypi.org/simple/ NSEDownload==0.1.2`.
2. Create a wrapper in `eqats/data_engines/nse_download.py` exposing methods like `fetch_stock(symbol, start_date, end_date)` and `fetch_index(index_name, start_date, end_date, index_type="")`.
3. Integrate the return‑calculation functions as a pre‑processor in `eqats/signals/returns.py` to generate momentum‑style signals.
4. No direct risk components are provided; the risk engine remains unchanged and can consume the fetched data for limit checks, VaR, etc.

## Benefits
- Immediate access to NSE historical data without building custom scrapers.
- Data arrives as ready‑to‑use pandas DataFrames, streamlining backtesting and research.
- Lightweight dependencies (requests, beautifulsoup4, numpy, pandas) keep the integration low‑overhead.
