# Integration Blueprint for hakija into eqats

## Overview
The hakija repository provides a simple Python script to download NSE End‑of‑Day (EOD) equity and index data directly from the NSE website and store it as ASCII files compatible with MetaStock. This capability can be leveraged as a data‑engine component within the eqats quantitative trading platform to feed historic and daily market data into eqats’ data lake.

## Proposed Integration
1. **Data Ingestion Layer**
   - Wrap the existing hakija downloader into a reusable Python module (e.g., `eqats.data.nse_downloader`).
   - Expose a function `fetch_eod(symbol: str, start_date: str, end_date: str) -> pd.DataFrame` that returns a DataFrame with OHLCV columns.
   - Internally, the module calls the hakija HTTP endpoints, parses the CSV/ASCII response, and returns the data.
   - Add retry logic, timeout handling, and logging using eqats’ standard utilities.

2. **Storage & Format**
   - Instead of writing raw ASCII files to the local directory, persist the fetched data to eqats’ preferred storage (e.g., Parquet files on S3 or a local data lake) partitioned by date and symbol.
   - Provide a conversion step that transforms the MetaStock‑compatible ASCII format into eqats’ canonical schema (timestamp, open, high, low, close, volume).

3. **Orchestration**
   - Schedule daily runs via eqats’ orchestration engine (Airflow, Prefect, or Dagster) to pull the latest EOD data after market close.
   - For back‑filling, expose a CLI command that invokes the downloader for a historical date range.

4. **Metadata & Catalog**
   - Register the NSE EOD dataset in eqats’ data catalog (e.g., using AWS Glue or a custom metadata service) with schema description and source provenance (hakija, NSE).

5. **Testing & Validation**
   - Implement unit tests that mock the NSE HTTP responses to verify correct parsing.
   - Add data quality checks (e.g., non‑negative prices, monotonic dates) before persisting.

## Benefits
- **Automated Data Feed**: Eliminates manual download steps, ensuring eqats always has up‑to‑date NSE data.
- **Reusability**: The downloader can be reused across strategies that require NSE equities or indices.
- **Reliability**: Leveraging hakija’s proven HTTP fetching logic reduces development effort.

## Considerations
- The hakija script currently writes files to the program’s directory; the integration will need to modify this behavior to write to eqats’ storage abstraction.
- NSE may impose rate limits; incorporate eqats’ rate‑limiting and retry mechanisms.
- Ensure compliance with NSE’s terms of service when scaling the downloader.

## Conclusion
By encapsulating hakija’s downloading functionality into a well‑defined eqats data engine, the platform gains a reliable source of NSE EOD market data, enabling downstream signal generation, backtesting, and live trading workflows.