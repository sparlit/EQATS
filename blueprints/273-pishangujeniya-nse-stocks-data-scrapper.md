# Integration Blueprint for NSE Stocks Data Scrapper into eqats

## Overview
The NSE Stocks Data Scrapper is a TypeScript/Node.js Express application that exposes two key scraping endpoints:
- GET /company/scrap_company_details – returns detailed information about NSE listed companies.
- GET /stock/scrap_stock_history – returns historical OHLCV data for a given stock.

These endpoints can be leveraged by eqats as a reliable, on-demand market-data ingestion layer for Indian equities.

## Proposed Integration Steps

1. Wrap the Scraper as a Data Source Service
   - Deploy the scraper (or containerize it) within the eqats infrastructure.
   - Create a thin adapter in eqats' data-engines module that calls the scraper’s HTTP endpoints.
   - The adapter should normalize the JSON payloads into eqats' canonical market-data format (e.g., {symbol, timestamp, open, high, low, close, volume} for history and {symbol, name, sector, ...} for company details).

2. Ingestion Pipeline
   - Use eqats' scheduler (cron or event-driven) to trigger the adapter at desired frequencies (e.g., end-of-day for history, intraday for real-time if the scraper supports it).
   - Store raw responses in eqats' raw data lake (e.g., S3 or local storage) for auditability.
   - Persist normalized data into eqats' time-series database (e.g., InfluxDB, TimescaleDB) via the existing data-engine writers.

3. Error Handling & Retry
   - The adapter should implement exponential back-off and respect any rate-limits implied by the scraper (the README does not specify limits; assume polite usage).
   - Log failures to eqats' monitoring system and alert if consecutive failures exceed a threshold.

4. Testing & Validation
   - Import the provided Postman collection into eqats' CI pipeline to verify endpoint availability after each deployment.
   - Implement unit tests that mock the scraper’s responses to ensure the adapter’s transformation logic is correct.

5. Configuration
   - Expose endpoint URL and optional API key (if authentication is added later) via eqats' config service (e.g., env vars NSE_SCRAPER_BASE_URL).
   - Allow enabling/disabling the NSE data source without code changes.

## Benefits
- Alternative Data Source: Provides a free, programmatic way to fetch NSE data without relying on costly vendors.
- Flexibility: Being a separate service, it can be updated or replaced independently of eqats' core.
- Reproducibility: The scraper’s source code is available, allowing eqats to audit or enhance the extraction logic.

## Limitations
- The scraper relies on web scraping; changes to NSE website layout may break it.
- No explicit rate-limiting or authentication is documented; production use should monitor for blocking.
- No built-in signal generation or order execution; it serves purely as a data feed.

## Conclusion
By integrating the NSE Stocks Data Scrapper as a market-data ingestion service, eqats can expand its coverage to Indian equities with minimal development effort, leveraging existing TypeScript/Node.js infrastructure and the provided Postman collection for rapid validation.