# Integration Blueprint for YFinance-stock-history into eqats

## Overview
The repository provides a simple Python script that extracts NSE stock symbols from `equity.csv`, fetches historical price data via YFinance (using `ystockquote.py`), and stores the results in SQLite databases (`company.db` and `history.db`). It outlines future work to switch to Google Finance for real‑time data, run multiple instances, and move to MySQL for concurrent access.

## Data Engine Features
- **Symbol ingestion**: Reads `equity.csv` to obtain the list of NSE tickers.
- **Historical market data**: Calls YFinance through `ystockquote.py` to download daily OHLCV series.
- **Storage**: Writes each symbol’s history to SQLite tables; separate DBs for company metadata and price history.
- **Planned enhancements**: Migration to MySQL to support concurrent writers/workers; replacement of YFinance with GFinance for low‑latency real‑time quotes.

## Signal & Execution Logic
*The repository does not contain any signal generation, strategy back‑testing, or order execution components.*

## Risk Engineering
*The repository lacks risk‑limit checks, position‑sizing algorithms, or real‑time risk monitoring.*

## How to Integrate into eqats
1. **Data Engine Layer**
   - Replace eqats’ current CSV‑based symbol loader with the `equity.csv` parser from `history.py`.
   - Wrap the YFinance call (`ystockquote.get_historical_prices`) in eqats’ data‑ingestion adapter, returning a standardized pandas DataFrame.
   - Store the incoming bars in eqats’ time‑series store (e.g., TimescaleDB) by first persisting to SQLite/MySQL as a staging layer, then batch‑loading into the primary store.
   - For real‑time needs, plug the planned GFinance module into eqats’ live‑feed adapter, subscribing to tick updates and publishing to the internal message bus.
   - Enable multiple ingestor workers by configuring the MySQL backend; each worker can pull a subset of symbols from the symbol table, preventing duplicate downloads.

2. **Signal & Execution Layer**
   - Since the source repo provides no signals, eqats will continue to use its existing strategy framework (e.g., vectorized indicators, ML models) on the ingested data.
   - The historical data made available by this integration can be used to back‑test those strategies via eqats’ back‑testing engine.

3. **Risk Engineering Layer**
   - No risk components are present; eqats should apply its existing risk‑management module (position limits, VaR, stop‑loss) to the data coming from this source.
   - Future extensions could add a simple risk‑monitor that reads the SQLite/MySQL staging tables for anomalous price jumps and triggers alerts.

## Implementation Steps
- Fork the repository and add a `setup.py` or `pyproject.toml` for easy installation.
- Refactor `history.py` into two modules: `symbol_loader.py` and `market_data_fetcher.py`.
- Add an interface class `eqats.data.ingest.YFinanceSource` that eqats can instantiate.
- Write unit tests using `pytest` to verify that data fetched matches a known sample.
- Deploy the MySQL schema (provided in the repo’s TODO) and adjust the storage writer to use SQLAlchemy.
- Integrate the module into eqats’ data‑pipeline configuration (e.g., add a new source under `data_sources:` in the YAML config).
- Run a smoke test: ingest one month of NSE data, store it, and run an existing eqats strategy to confirm the pipeline works.

## Conclusion
The YFinance‑stock‑history repo supplies a solid, reusable data‑engine for pulling NSE equity history into a relational store. By adopting its symbol loader and YFinance wrapper—and later its MySQL/GFinance upgrades—eqats can quickly expand its coverage of Indian equities while retaining its existing signal, execution, and risk layers.