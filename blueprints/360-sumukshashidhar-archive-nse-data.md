# Integration Blueprint for NSE Minute Data

## Overview
Integrate minute-by-minute historical data from the NSE into the eqats trading system.

## Components
- **Data Engine**: nse_minute_data module provides functions to load ticker lists and minute bar data.
- **Signal & Execution**: Example strategies use the loaded data to generate signals.
- **Risk Engineering**: Utilities to compute volatility, VaR, and liquidity metrics.

## Data Flow
1. Ticker list (ticker.csv) is loaded into memory.
2. For a given symbol, minute data is read from data/<SYMBOL>.csv.
3. Data is converted into eqats' internal TimeSeries format.
4. Signals and risk metrics are computed downstream.

## API
- load_tickers(path: &str) -> Result<HashMap<String, String>, io::Error>
- load_minute_bars(symbol: &str, data_dir: &str) -> Result<Vec<MinuteBar>, io::Error>