# Integration Blueprint: nse-historical-data into eqats

## Overview
The `nse-historical-data` repository provides a Node.js service that downloads National Stock Exchange (NSE) historical equity data and stores it as CSV files (`YYYY-MM-DD.csv`) in a Google Cloud Storage bucket. It can be run locally, deployed as a Google Cloud Function, or invoked via HTTP for backfilling. The data can be queried in BigQuery, deduplicated with SQL, and persisted to Cloud Datastore.

## Data Engine Features
- **Ingestion**: `node index.js [date]` fetches NSE data for a given date or today.
- **Storage**: CSV files are written to a configurable GCS bucket.
- **Cloud Function**: HTTP endpoint `getQuotesByDate` accepts a `date` query parameter.
- **Backfill Script**: Bash loop demonstrates daily calls to the Cloud Function.
- **BigQuery Integration**: Example SQL for counting records, creating unique‑date views, and deduplication.
- **Datastore Persistence**: `saveQuoteToDatastore` function automatically saves each quote.

## Signal & Execution Logic
*No signal generation, strategy, or order‑execution components are present in this repository.*

## Risk Engineering
*No risk‑limit, position‑sizing, or monitoring features are included.*

## Integration Steps for eqats
1. **Deploy the fetcher**
   - Package the Node.js code as a Cloud Run service or Cloud Function.
   - Set environment variable `GCS_BUCKET` to an eqats‑dedicated bucket (e.g., `eqats-nse-raw`).
   - Enable authentication via default application credentials.

2. **Schedule daily ingestion**
   - Use Cloud Scheduler to trigger the HTTP endpoint each market‑close with the previous trading day’s date (or use the CLI locally for ad‑hoc runs).
   - For historical backfill, adapt the provided bash loop, replacing the URL with the deployed endpoint.

3. **Land raw CSV in eqats data lake**
   - The service drops `YYYY-MM-DD.csv` files directly into the bucket.
   - Configure a Cloud Storage trigger (or a nightly Dataflow job) to load new CSVs into a BigQuery table `eqats.nse_raw.historical_data` using `bq load` with autodetect schema.

4. **Prepare analysis‑ready tables**
   - Run the supplied SQL to create a deduplicated view:
     ```sql
     CREATE OR REPLACE VIEW `eqats.nse_data.nse_historical_data_unique` AS
     SELECT *
     FROM (
       SELECT *,
              ROW_NUMBER() OVER (PARTITION BY SYMBOL, TIMESTAMP) AS row_number
       FROM `eqats.nse_data.nse_historical_data`
       WHERE SERIES = 'EQ'
     )
     WHERE row_number = 1;
     ```
   - Optionally materialize the view into a table for faster access.

5. **Leverage Datastore for low‑latency lookups**
   - If eqats needs real‑time quote access, enable the `saveQuoteToDatastore` call (already present) to write each record to a Kind `NSEQuote`.
   - Index on `symbol` and `timestamp` for quick retrieval.

6. **Build signals and execution**
   - With the historical data now available in BigQuery/Datastore, eqats can develop Python/Java/Node‑based strategy modules that read the data, generate signals, and route orders via its execution engine.
   - No changes to the fetcher are required.

7. **Apply risk controls**
   - Risk limits, position sizing, and monitoring should be implemented in eqats’ risk engine, consuming the same data feeds or signal outputs.
   - The fetcher does not provide risk features, so eqats must add its own.

## Maintenance
- Update the Node.js dependencies (`npm update`) to stay current with the `google-cloud-storage` client.
- Monitor Cloud Function logs for fetch failures; set up alerting on missing CSV files.
- Periodically review the deduplication SQL to accommodate schema changes from NSE.

## Summary
By adopting `nse-historical-data` as the ingestion layer, eqats gains a reliable, cloud‑native pipeline for NSE historical equity data, stored in GCS, queryable in BigQuery, and optionally cached in Datastore. Signal generation, execution, and risk management remain the responsibility of eqats’ existing modules, keeping a clean separation of concerns.