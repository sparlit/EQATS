# Integration Blueprint for akshayraje/get-nse-bhavcopy into eqats

## Overview
The repository provides a simple PHP script that fetches the National Stock Exchange (India) end‑of‑day Bhavcopy CSV and loads it into a MySQL table. This functionality aligns with the **Data Engines** domain of eqats, specifically market data ingestion and storage.

## Data Engines Features
- **Ingestion**: HTTP GET to NSE India URL, handling both current date and user‑specified date (format DD-Mon-YYYY).
- **Parsing**: Reads CSV directly (via fgetcsv) and maps columns to MySQL fields.
- **Storage**: Configurable MySQL connection; creates/uses table defined in `create-table.sql`.
- **Execution Modes**: Can be invoked via web browser (GET) or command line (`php script.php`), making it easy to schedule with cron.
- **Feedback**: Outputs success/error messages suitable for logging.

## How to Integrate into eqats
1. **Wrap the PHP script as a reusable data‑engine component**
   - Convert the script into a class or service that eqats can instantiate (e.g., `NseBhavcopyFetcher`).
   - Expose a method `fetch(date?: string): Promise<void>` that returns a promise for async handling.

2. **Leverage eqats’ existing configuration system**
   - Move database credentials to eqats’ config (YAML/ENV) and inject via dependency injection.
   - Allow the date format to be configurable (default to today).

3. **Schedule via eqats’ job scheduler**
   - Register a daily job (e.g., at 18:30 IST) that calls the fetcher.
   - Use eqats’ monitoring hooks to log success/failure and trigger alerts on failure.

4. **Data model mapping**
   - Map the Bhavcopy columns to eqats’ canonical market‑data schema (symbol, series, open, high, low, close, last, prevclose, tottrdqty, tottrdval, timestamp, etc.).
   - If eqats already has a market‑data table, create an adapter or migration script.

5. **Extension points**
   - **Historical backfill**: Accept a date range and loop through dates to populate historic data.
   - **Alternative sources**: Abstract the HTTP client to allow swapping in other vendors (e.g., BSE, NSE API).
   - **File fallback**: Save raw CSV to object storage (S3) for audit before DB load.

## Signal & Execution Logic
The repository does not contain any signal generation, strategy logic, or order execution components. Hence, no direct mapping to the **Signal & Execution Logic** domain.

## Risk Engineering
Similarly, there are no risk‑limit checks, position sizing, or risk monitoring features. No direct mapping to the **Risk Engineering** domain.

## Summary
By encapsulating the PHP fetcher as a pluggable data‑engine service, eqats can reliably obtain NSE end‑of‑day equity data each trading day, store it in its MySQL‑based market‑data warehouse, and make it available downstream for strategy development, backtesting, and live trading.