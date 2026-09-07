# Integration Blueprint for NSEDatabase into eqats

## Overview
The NSEDatabase repository provides a lightweight pipeline to download historical NSE equity bhav copies, store them in a local database, and expose the data as pandas DataFrames. It also includes a simple reporting script that identifies positively moving stocks over a short horizon.

## Data Engine Integration
1. **Ingestion** – Use `getbhav.py` to pull bhav copies for desired periods (e.g., `python getbhav.py -getMonth 02 2017`). eqats can schedule this as a daily/weekly job to keep its market‑data cache up‑to‑date.
2. **Storage** – Run `csvtodb.py -add <file>` or `-addDir <folder>` to insert CSV rows into a SQLite database (or any DB supported by the script). eqats can point its data‑engine to this SQLite file, leveraging the existing schema.
3. **Retrieval** – Call `csvtodb.py -get <Symbol>` or `-getMany <Sym1,Sym2,...]` to obtain a pandas DataFrame. eqats can wrap these calls in a data‑feed adapter that returns OHLCV data in the format expected by its strategy engine.
4. **Benefits** – Eliminates the need to build a custom NSE scraper; provides reliable, versioned historical data; supports incremental updates.

## Signal & Execution Logic Integration
- The `report.py` script (`python report.py -posGain 5 20`) outputs a list of symbols that have gained positively over the last 5 days, together with their 20‑day change. eqats can treat this list as a **long‑only entry signal**.
- Integration steps:
  1. Schedule `report.py` to run after the market close.
  2. Capture its output (CSV or plain text) and feed it into eqats’ signal module as a binary signal (1 for listed symbols, 0 otherwise).
  3. Combine with other signals (e.g., volatility, momentum) within eqats’ signal‑aggregation framework.
  4. Optionally, extend the script to output additional metrics (e.g., RSI, volume) for more sophisticated signal generation.

## Risk Engineering Integration
- The repository does not contain explicit risk‑limit, position‑sizing, or monitoring features. Consequently, no direct risk‑engineering components can be imported. eqats should continue to use its own risk‑management modules (VaR, max drawdown, leverage limits) when employing data or signals from NSEDatabase.

## Implementation Steps
1. **Clone the repo** and add it as a submodule or dependency in the eqats codebase.
2. **Create a wrapper class** `NSEDataFeed` that:
   - Calls `getbhav.py` with configurable date ranges.
   - Invokes `csvtodb.py` to persist new CSVs.
   - Exposes a method `get_ohlcv(symbol, start, end)` returning a DataFrame.
3. **Develop a signal adapter** `NSEPositiveMomentumSignal` that runs `report.py` and maps its output to eqats’ signal interface.
4. **Unit‑test** the wrapper against a known month of data to ensure data integrity.
5. **Deploy** the ingestion pipeline as a cron job or Airflow DAG to keep the database refreshed.
6. **Monitor** latency and data quality; fallback to alternative data sources if NSE fails.

## Example Usage (pseudo‑code)
```python
from eqats.data_engines import NSEDataFeed
feed = NSEDataFeed(db_path='nse.db')
df = feed.get_ohlcv('RELIANCE', '2023-01-01', '2023-12-31')

from eqats.signals import NSEPositiveMomentumSignal
signal = NSEPositiveMomentumSignal(lookback_short=5, lookback_long=20)
signal_today = signal.generate()  # returns dict {symbol: 1/0}
```

## Conclusion
By integrating NSEDatabase’s robust data‑engine and simple positive‑momentum reporter, eqats gains instant access to clean NSE historical data and a ready‑made long‑only signal, accelerating strategy development while keeping risk‑management within its existing framework.
```
