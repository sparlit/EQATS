# Integration Blueprint for NSE Stock Price Crawler into eqats

## Overview
The NSE Stock Price Crawler provides a robust data ingestion pipeline for historical Nairobi Securities Exchange (NSE) equity prices from September 2006 to April 2022. It can be repurposed as a market‑data engine within the eqats quantitative trading platform to supply clean, structured price series for Kenyan equities.

## Data Engine Integration
1. **Ingestion Layer**
   - Replace the crawler’s output directory (`data/`) with eqats’ raw‑data lake (e.g., `eqats/data/raw/nse/`).
   - The crawler’s `getData.py` script can be invoked as a scheduled job (cron or Airflow) to pull incremental updates for new trading days.
   - HTTP requests are made to `https://live.mystocks.co.ke/`; the script already handles pagination and error logging (404s) to `errorlog/error.log`.
   - In eqats, we would wrap the existing logic in a reusable Python module (`nse_crawler.ingest`) that returns pandas DataFrames and writes them to the lake in Parquet format for efficient downstream consumption.

2. **Storage & Organization**
   - The crawler naturally creates four hierarchies: Daily → Monthly → Yearly → Company.
   - In eqats we can preserve this hierarchy or flatten to a single partitioned dataset (e.g., partitioned by `date` and `symbol`).
   - Using the existing CSV structure as a staging step, we can convert each file to Parquet with schema:
     ```
     symbol: string
     name: string
     date: date
     low: double
     high: double
     close: double
     prev_close: double
     volume: int64
     ```
   - Metadata (exchange, currency) can be added during ingestion.

3. **Error Handling & Monitoring**
   - The crawler’s `error.log` captures 404s (e.g., holidays, missing pages).
   - In eqats we would forward these logs to a monitoring system (e.g., Prometheus alertmanager) and treat persistent 404s as data‑quality incidents.

## Signal & Execution Logic
- The repository does **not** contain any signal generation, strategy logic, or order‑execution components.
- Therefore, no direct integration points exist in the Signal & Execution Logic domain. Strategies built in eqats can consume the NSE price data produced by this engine.

## Risk Engineering
- Similarly, there are no risk‑limit, position‑sizing, or risk‑monitoring features.
- Risk modules in eqats (e.g., VaR, exposure limits) will rely on the ingested NSE data as an input.

## Deployment Steps
1. Fork the repository or copy `getData.py` and supporting files into the eqats codebase under `engines/data/nse/`.
2. Create a thin wrapper that:
   - Reads start/end dates from eqats’ configuration (YAML/JSON).
   - Calls the crawler’s core functions.
   - Writes output to eqats’ data lake (preferably Parquet on S3 or local filesystem).
   - Returns ingestion status and logs any errors.
3. Schedule the wrapper via eqats’ orchestration layer (e.g., Airflow DAG) to run after each market close.
4. Add unit tests that verify the schema of the produced DataFrames and that error logs are handled appropriately.

## Benefits
- Provides a reliable, low‑latency source of historical NSE equities for backtesting and live trading.
- Leverages existing, battle‑tested crawling logic, reducing development effort.
- Centralizes error logging, facilitating data‑quality monitoring.

## Limitations
- Data coverage ends April 2022; for live trading an extension to fetch recent days would be required (the same endpoint likely still serves current data).
- Holiday adjustments (Eid al‑Adha, Eid Fitr) are not automatically removed; a calendar filter should be applied downstream.

---
*This blueprint maps the crawler’s data‑engine capabilities to eqats’ ingestion pipeline while noting the absence of signal/execution and risk features.*