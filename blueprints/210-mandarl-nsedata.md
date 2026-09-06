# Integration Blueprint for mandarl/nsedata into eqats

## Repository Overview
- **Purpose**: Download NSE bhavcopy files and import historical equity/futures data into AmiBroker.
- **Primary Language**: Visual Basic (VB scripts).
- **Key Functionality**: Automated HTTP download of daily bhavcopy ZIPs, extraction, CSV parsing, format conversion, and AmiBroker import via its COM interface.

## Data Engine Features
1. **Historical Market Data Ingestion** – Scripts fetch bhavcopy from NSE archives for a configurable date range.
2. **Data Parsing & Normalization** – Extracts CSV columns (symbol, date, open, high, low, close, volume) and maps them to AmiBroker field names.
3. **Storage & Import** – Writes AmiBroker-compatible ASCII files or directly populates the AmiBroker database using its automation interface, enabling immediate use in eqats’ backtesting engine.

## How to Integrate into eqats
- **Replace/augment eqats’ current data loader** with the VB download/import pipeline to source NSE equities and futures directly.
- **Expose a thin wrapper** (e.g., Python or C#) that calls the VB scripts via command line, returning success/failure status for orchestration within eqats’ data‑engine layer.
- **Store the downloaded raw bhavcopy** in eqats’ data lake (e.g., Parquet partitioned by date) while also maintaining the AmiBroker import for users who rely on that platform.
- **Add metadata tracking** (download timestamp, source URL) to enable data lineage and versioning.

## Extensions & Enhancements
- **Incremental Updates**: Modify the script to only download missing dates, reducing bandwidth.
- **Validation Layer**: Add checksum verification of downloaded ZIPs and basic OHLC sanity checks before import.
- **Unified Format**: Convert the imported data into eqats’ internal canonical format (e.g., Arrow/Parquet) to avoid duplication.
- **Scheduler Integration**: Hook into eqats’ job scheduler (e.g., Airflow, Prefect) to run the download daily after market close.

## Signal & Execution Logic
- The repository contains no signal generation, strategy code, or order execution components. Therefore, no direct integration points exist in this domain; eqats would continue to rely on its existing signal/execution modules.

## Risk Engineering
- Likewise, there are no risk limits, position sizing, or risk monitoring features. Integration would not add risk‑engineering capabilities; eqats’ existing risk framework should be retained.

## Summary
By incorporating the NSE bhavcopy download and AmiBroker import scripts, eqats gains a reliable, automated source of Indian equity and futures historical data, enriching its backtesting universe while preserving its existing signal, execution, and risk layers.