# Integration Blueprint for option_chain_analyzer into eqats

## Overview
The `option_chain_analyzer` repository provides a Java‑based utility to fetch live NSE option chain data and persist it into a ClickHouse database. This capability aligns with the **Data Engines** domain of eqats, offering a ready‑made ingestion pipeline for Indian equity derivatives market data.

## Key Features to Leverage
- **NSE Option Chain Fetcher** – HTTP client that queries the NSE public option chain endpoint and returns structured JSON.
- **ClickHouse Writer** – Uses the ClickHouse JDBC driver to insert option chain snapshots into a predefined schema (e.g., table `option_chains` with columns for timestamp, symbol, strike, expiry, call/put prices, Greeks, etc.).
- **Configurable Schedule** – Simple main class can be invoked via cron or eqats scheduler to capture data at desired frequencies (e.g., every minute during market hours).

## How to Integrate
1. **Package as a Library**
   - Convert the existing `main` class into a reusable service (e.g., `NseOptionChainFetcherService`) exposing a method `fetchAndStore(LocalDateTime timestamp)`.
   - Publish the JAR to eqats’ internal artifact repository or include as a submodule.

2. **Integrate into eqats Data Engine**
   - In eqats’ market‑data ingestion layer, register a new data source of type `NSE_OPTION_CHAIN`.
   - The source will call the service on each tick, passing the received data to eqats’ normalized market‑data schema (or directly to ClickHouse if eqats already uses ClickHouse for raw storage).
   - Map NSE fields to eqats canonical fields: `underlying_symbol`, `instrument_type`, `expiry_date`, `strike_price`, `bid`, `ask`, `last_price`, `volume`, `open_interest`.

3. **Schema Alignment**
   - Ensure the ClickHouse table used by the analyzer matches eqats’ raw option‑chain table (if exists) or create a view that transforms the stored JSON into eqats’ normalized format.
   - Example table definition:
     ```sql
     CREATE TABLE eqats.raw_nse_option_chain (
         ingest_time DateTime,
         symbol String,
         expiry Date,
         strike Float64,
         option_type String, -- 'CE' or 'PE'
         bid Float64,
         ask Float64,
         last Float64,
         volume UInt64,
         open_interest UInt64
     ) ENGINE = MergeTree()
     PARTITION BY toYYYYMM(ingest_time)
     ORDER BY (symbol, expiry, strike, option_type, ingest_time);
     ```

4. **Scheduling & Orchestration**
   - Use eqats’ existing scheduler (e.g., Airflow, Prefect, or internal cron wrapper) to trigger the fetcher service during NSE market hours (09:15–15:30 IST).
   - Add health‑checks: verify HTTP response status, validate JSON schema, and log insertion counts.

5. **Testing & Validation**
   - Unit test the fetcher with mock NSE responses.
   - Integration test by running against a temporary ClickHouse instance and asserting row counts.
   - Validate that stored data can be joined with eqats’ equity price feeds for downstream analytics.

## Benefits
- **Low‑latency ingestion** – Direct HTTP to NSE minimizes reliance on third‑party vendors.
- **Scalable storage** – ClickHouse columnar engine efficiently handles high‑frequency option‑chain snapshots.
- **Reusability** – The same service can feed multiple eqats strategies that require option‑chain data (e.g., volatility surfaces, skew analysis, gamma exposure).

## Limitations & Future Work
- The current code lacks authentication headers; NSE may block excessive requests – implement rate‑limiting and retry logic.
- No built‑in handling of corporate actions (splits, dividends); downstream eqats modules should adjust strikes accordingly.
- Extend the fetcher to also capture futures‑option data or index options (NIFTY, BANKNIFTY) by adjusting endpoint parameters.

## Conclusion
By wrapping the existing fetching and ClickHouse persistence logic into a reusable service and plugging it into eqats’ data‑engine layer, we gain a robust, self‑hosted pipeline for NSE option‑chain market data—fueling downstream signal generation, risk calculations, and strategy back‑testing without external data‑vendor costs.
