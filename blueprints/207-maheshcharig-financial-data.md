# Integration Blueprint for financial-data into eqats

## Overview
The `financial-data` repository supplies minute‑level NSE index data (1‑, 3‑, and 5‑minute bars). It can be used as a data engine to feed historical and real‑time market data into the eqats quantitative trading system.

## Data Engine Integration
- **Ingestion**: Use the existing download scripts (or adapt them) to pull NSE index data from the NSE website or public APIs and store it in a format eqats expects (e.g., CSV, Parquet, or a time‑series database).
- **Storage**: Map the downloaded files into eqats's data lake under `data/market/NSE/<index>/<interval>/`.
- **Metadata**: Attach metadata such as symbol, interval, timestamp, and source.

## Signal & Execution Logic
The repository does not contain signal generation or order execution code. Consequently, eqats would rely on its own strategy modules to consume the data provided by this engine.

## Risk Engineering
No risk‑limits, position‑sizing, or monitoring utilities are present. Risk controls should be implemented within eqats's risk engine using the ingested data.

## Implementation Steps
1. Clone the repo and examine the data acquisition scripts.
2. Wrap the download logic in an eqats‑compatible data‑engine plugin (e.g., a Python class implementing `eqats.data.BaseFeed`).
3. Schedule periodic runs (via cron or eqats scheduler) to keep the minute‑bar dataset up‑to‑date.
4. Validate data integrity (check for missing bars, correct timestamps).
5. Feed the data into eqats’s backtesting/live trading pipelines.

## Benefits
- Provides reliable, high‑frequency NSE index data without building a custom scraper.
- Enables eqats to test intraday strategies on Indian market indices.
- Reduces data‑acquisition effort, allowing focus on signal development and risk management.

## Considerations
- Verify the data source’s terms of use and rate limits.
- Ensure timezone handling matches eqats's expectations (IST).
- Monitor for changes in the NSE website structure that could break the download scripts.
