# Integration Blueprint for tickdownload into eqats

## Overview
The `tickdownload` repository offers a set of Python utilities for acquiring Indian equity market data from the National Stock Exchange (NSE) and Bombay Stock Exchange (BSE). Core capabilities include downloading historical OHLCVD series, corporate actions (bonus/split), index data, and building a master ticker list. Data are persisted in an SQLite3 database, making them readily queryable.

## Data Engines Integration
- **Market Data Ingestion**: Replace or supplement eqats’ current data feeds with the NSE/BSE downloaders (`get_stocks_nse`, `get_stocks_bse`) to populate eqats’ historical price database for Indian equities.
- **Index Data**: Use `get_indices_nse` and `get_indices_bse` to fetch benchmark indices (e.g., NIFTY 50, SENSEX) for strategy backtesting or regime detection.
- **Corporate Actions**: Integrate `corp_actions_nse` (preferred) and, where needed, `corp_actions_bse` to adjust historical prices for bonuses, splits, dividends, ensuring clean backtest inputs.
- **Master Stock List**: Leverage `all_stocks_list.py` to maintain an up-to-date universe of liquid stocks (NSE EQ/BE series, BSE Groups A/B/T) that can drive eqats’ universe selection and screening modules.
- **Storage**: The existing SQLite3 staging can be mapped to eqats’ data lake; alternatively, extracted DataFrames can be written directly to eqats’ preferred storage (e.g., Parquet, TimescaleDB) via pandas.

## Signal & Execution Logic
The repository does not contain signal generation, strategy logic, or order execution components. Therefore, no direct integration points exist in this domain. eqats would continue to rely on its own signal/execution modules.

## Risk Engineering
Similarly, there are no risk‑limit, position‑sizing, or monitoring utilities in tickdownload. Risk‑related features would need to be sourced elsewhere or developed within eqats.

## Implementation Steps
1. **Wrap Downloaders**: Create thin adapters in eqats’ data‑ingest layer that call the relevant functions, standardizing output to a common schema (timestamp, open, high, low, close, volume, dividend, split).
2. **Corporate Action Adjustment**: Post‑download, apply bonus/split factors from `corp_actions_nse` to adjust price series before storing in eqats’ adjusted‑price tables.
3. **Universe Refresh**: Schedule a weekly run of `all_stocks_list.py` to refresh the list of tradable symbols; feed the output into eqats’ universe manager.
4. **Index Feed**: Pull index data daily to update eqats’ market‑regime indicators.
5. **Testing & Validation**: Compare downloaded OHLCVD against a known vendor source for a sample of tickers to verify correctness before production use.

## Limitations & Considerations
- The BSE corporate actions module (`corp_actions_bse`) is noted as incomplete; rely on NSE data where possible.
- Experimental HDF5 support (`scrip_to_h5`) is deprecated and should not be used.
- The repository is a work in progress; some NSE downloaders may be unreliable—prefer the bhavcopy‑based `get_stock_nse` as indicated.
- Ensure compliance with NSE/BSE data usage terms when redistributing or storing the data.

By incorporating these data‑engine utilities, eqats can expand its coverage to Indian equities with minimal development effort, while keeping signal, execution, and risk layers unchanged.