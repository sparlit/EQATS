# Integration Blueprint for NSEDownload into eqats

## Overview
NSEDownload is a lightweight Python library that fetches historical equity data from the National Stock Exchange (NSE) of India and returns it as a pandas DataFrame. It can be used as a data engine within eqats to supply Indian market data for backtesting, research, and live trading.

## Data Engine Integration
1. **Wrapper / Connector**
   - Create a new connector module `eqats/data/connectors/nse_download.py`.
   - Expose a function `fetch_nse_data(symbol: str, start: str, end: str) -> pd.DataFrame` that internally calls `NSEDownload.stocks.get_data`.
   - Standardize column names to eqats’ internal schema (e.g., rename `High Prices` → `high`, `Low Prices` → `low`, etc.).
   - Ensure the `Date` column is parsed to UTC datetime and set as index.
2. **Rate‑limit Handling**
   - Follow the library’s tip: insert a `time.sleep(5)` between calls for different symbols.
   - Implement a simple throttler or use `ratelimit` decorator to respect NSE’s request limits.
3. **Caching**
   - Optionally cache fetched DataFrames locally (e.g., using `pickle` or `parquet`) to avoid repeated downloads during development.
4. **Error Handling**
   - Catch HTTP errors, empty DataFrames, and raise custom `DataFetchError` for upstream handling.

## Usage in eqats
```python
from eqats.data.connectors.nse_download import fetch_nse_data
import pandas as pd

def load_nse(symbol, start, end):
    df = fetch_nse_data(symbol, start, end)
    # eqats expects columns: open, high, low, close, volume
    df = df.rename(columns={
        'Open Prices': 'open',
        'High Prices': 'high',
        'Low Prices': 'low',
        'Close Prices': 'close',
        'Total Traded Quantity': 'volume'
    })
    return df[['open','high','low','close','volume']]

# Example
reliance = load_nse('RELIANCE', '01-01-2023', '31-12-2023')
```

## Signal & Execution Logic
- No direct features; the connector feeds data to existing eqats signal modules (e.g., moving‑average crossover, ML models).

## Risk Engineering
- No direct features; risk limits, position sizing, and monitoring remain the responsibility of eqats’ risk engine.

## Deployment
- Add `NSEDownload` to `requirements.txt` or `environment.yml`.
- Ensure the connector is imported in the data‑loading registry so that eqats can select `nse` as a data source via configuration.

## Maintenance
- Monitor the upstream repository for changes to the NSE website (the library already notes updates to use the new NSE site and cookies).
- Submit issues or pull requests if the data schema changes.
```
