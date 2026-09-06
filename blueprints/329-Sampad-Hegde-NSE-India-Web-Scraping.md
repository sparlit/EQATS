# Integration Blueprint for Sampad-Hegde/NSE-India-Web-Scraping into eqats

## Overview
The repository provides Python utilities to scrape real-time and historical data from the National Stock Exchange (India) website. It offers symbol lookup, full‑market snapshots, intraday streams, and up‑to‑3‑year historical series. These capabilities map directly onto the **Data Engines** domain of eqats, enabling eqats to ingest Indian equity market data for strategy research, backtesting, and live trading.

## Mapped Features

| Feature | Function (as in repo) | eqats Data Engine Role |
|---------|-----------------------|------------------------|
| `getId` | Resolve a company/common name to its NSE security ID (e.g., `'tata motors'` → `'TATAMOTORSEQN'`). | Symbol resolution service – feeds the instrument master. |
| `getTodayData` | Returns `(nifty_data, companies_data)` for all listed securities as a CSV‑ready tuple. | Real‑time market snapshot engine – can populate eqats’ `market_snapshot` table or feed a streaming topic. |
| `intraDay` (via `Intra_Day` class) | Provides timestamped intraday price series for a given security ID or NIFTY index from 09:00 AM to current time. | Live intraday feed – can be hooked to eqats’ `tick_handler` or `bar_builder` for minute‑level bars. |
| `getHistoryData` / `niftyHistoryData` | Retrieves daily OHLCV data for a stock or index (default 1‑year window, configurable up to ~3 years). | Historical data loader – supplies eqats’ backtesting engine and feature store. |

## Integration Steps

1. **Wrapper Module**
   Create `eqats/data_engines/nse_india.py` that re‑exports the above functions, adding eqats‑standard typing (e.g., returning `pd.DataFrame` with columns `['timestamp','open','high','low','close','volume']`).

2. **Instrument Master Sync**
   On startup, call `getId` for each ticker in eqats’ universe to populate the `instrument` table with NSE IDs. Cache results to reduce API calls.

3. **Snapshot Ingestion**
   Schedule a periodic job (e.g., every 5 minutes during market hours) that invokes `getTodayData`. Convert the returned tuple into a DataFrame and upsert into eqats’ `market_snapshot` table.

4. **Live Intraday Streaming**
   For each active instrument, instantiate `Intra_Day(security_id)` and invoke `intraDay()` in a loop (or use callbacks if the repo supports streaming). Publish each tick to eqats’ internal message bus (e.g., Redis stream) where the `tick_handler` aggregates to bars.

5. **Historical Backfill**
   When a new instrument is added, run `getHistoryData(symbol, from_date, to_date)` to pull the maximal available history and load it into eqats’ `historical_prices` table. This data fuels the backtesting engine and feature generation pipelines.

6. **Error Handling & Rate Limits**
   Wrap all calls with retry logic and respect NSE’s anti‑scraping measures (e.g., random delays, session headers). Log failures to eqats’ monitoring system.

## Benefits

- **Unified Indian Market Access** – eqats gains a reliable source for NSE data without building a custom scraper.
- **Rapid Prototyping** – Researchers can instantly test strategies on live intraday or historical data.
- **Scalable** – The wrapper can be swapped for the newer `Bharat-sm-data` library if higher performance is needed.

## Caveats

- The repository is marked as deprecated in favor of `Bharat-sm-data`; consider migrating to that library for better maintenance.
- Web scraping may break if NSE changes its HTML/JSON endpoints; implement versioned adapters and unit tests against mock responses.

## Conclusion
By integrating the NSE‑India‑Web‑Scraping utilities into eqats’ Data Engines layer, we extend eqats’ coverage to Indian equities, enabling end‑to‑end workflows from data ingestion through signal generation to execution and risk management.