# Integration Blueprint: Financial Info Extractor -> eqats

## Repository Overview
- **Name**: Financial-Info-Extractor
- **Primary Language**: Python
- **Key Libraries**: BeautifulSoup, Requests, Selenium, PhantomJS
- **Purpose**: Scrapes fundamental financial data (balance sheet, cash flow, quarterly/half-yearly earnings, key ratios, profit-loss) for the top 500 NSE companies and exports each dataset as CSV files.

## Core Features Relevant to eqats
1. **URL Discovery** – Uses Selenium/PhantomJS to navigate the Religare site and collect the list of company URLs.
2. **HTML Parsing** – BeautifulSoup extracts tables containing financial statements.
3. **Data Export** – Writes each statement type (consolidated & standalone) to separate CSV files.
4. **Configurable Scope** – Can be limited to a subset of companies or specific statement types.

## How to Integrate into eqats (Data Engines Domain)
- **Ingestion Layer**: Replace or supplement eqats’ existing market-data ingestors with this scraper to pull fundamental data directly from the source.
- **Storage Layer**: Instead of raw CSVs, adapt the output to write into eqats’ preferred storage (e.g., PostgreSQL, TimescaleDB, or a feature store) by adding a thin wrapper that reads the generated CSV and upserts records.
- **Scheduler**: Hook the `url-extractor.py` -> `extract.py` pipeline into eqats’ cron or Airflow DAG to run daily/weekly, ensuring the fundamental dataset stays current.
- **Unified Schema**: Map the scraped columns to eqats’ canonical fundamental schema (e.g., ticker, statement_type, period, field_name, value) to enable seamless joining with price and alternative data.
- **Versioning**: Store each run’s CSV as a dated snapshot in a data lake (S3/GCS) to support back-testing and reproducibility.

## Signal & Execution Logic
The repository does not contain signal generation, strategy logic, or order-execution components. Therefore, no direct integration points exist in this domain. Fundamental data produced by the extractor can, however, serve as input to eqats’ signal-generation modules (e.g., factor models, valuation-based strategies).

## Risk Engineering
No risk-limit, position-sizing, or monitoring features are present. The extracted fundamentals can be used by eqats’ risk engine for credit-risk exposure, sector-concentration checks, or stress-testing, but the repo itself does not provide risk-specific functionality.

## Implementation Steps
1. **Fork & Clone** the repository into the eqats monorepo under `vendor/financial_info_extractor`.
2. **Create a Wrapper Script** (`eqats_ingest_fundamentals.py`) that:
   - Sets the PhantomJS/ChromeDriver path.
   - Invokes `url-extractor.py` and `extract.py`.
   - Reads the generated CSVs.
   - Transforms each row to eqats’ fundamental schema.
   - Upserts into the target database/table.
3. **Add Dependencies** to eqats’ `requirements.txt`: `beautifulsoup4`, `requests`, `selenium`, `phantomjs` (or use ChromeHeadless).
4. **Schedule** the wrapper via eqats’ existing orchestrator (e.g., Airflow DAG `fundamental_ingest_dag`).
5. **Validate** by running a small-sample ingest (e.g., top 10 NSE tickers) and checking row counts and data types.
6. **Document** the new data source in eqats’ data-catalog, noting refresh frequency and source URL.

## Considerations
- **Legal/ToS**: Scraping Religare’s website may be subject to terms of use; ensure compliance or seek an official data provider for production.
- **Maintainability**: The scraper relies on specific HTML structures; monitor for site changes and add fallback handling.
- **Performance**: Parallelize URL extraction (e.g., using threading) to reduce ingest time for the full 500-company list.
- **Headless Browser**: Consider swapping PhantomJS for Chrome/Chromium headless to avoid deprecated dependencies.

By plugging this extractor into eqats’ data-engine layer, the platform gains a reliable, automated source of Indian-equity fundamentals, enabling richer fundamental-based signals and more informed risk assessments.