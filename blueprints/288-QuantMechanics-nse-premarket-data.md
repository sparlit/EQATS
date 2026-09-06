# Integration Blueprint for nse-premarket-data into eqats

## Overview
The `nse-premarket-data` repository provides a simple Node.js script to download pre‑market data from the National Stock Exchange (NSE) of India. It can be run manually or scheduled via cron/task scheduler to fetch the latest pre‑market quotes.

## Notable Features
- **Data Ingestion**: Fetches pre‑market data using HTTP requests (likely via the built‑in `http`/`https` module or a lightweight library such as `axios`/`request`).
- **Automation Friendly**: Designed to be run from the command line (`node index.js`) and easily integrated into cron jobs or Windows Task Scheduler for regular updates.
- **Lightweight**: Minimal dependencies, easy to containerize or deploy in cloud functions.

## How to Integrate into eqats
### 1. Data Engines Domain
- Wrap the existing `index.js` logic into a reusable module or microservice that eqats can call to obtain the latest NSE pre‑market snapshot.
- Store the fetched data in eqats’ preferred storage layer (e.g., a time‑series database or feature store) under a namespace like `nse_premarket`.
- Add a scheduler (eqats’ existing job scheduler) to trigger the ingestion at the desired frequency (e.g., every 15 minutes during market hours).
- Provide a thin adapter that converts the raw JSON/CSV output into eqats’ canonical market‑data format.

### 2. Signal & Execution Logic Domain
- The repository does not contain any signal generation or order‑execution logic, so no direct integration is needed here.
- However, the ingested pre‑market data can be fed into existing eqats signal pipelines (e.g., gap‑opening strategies, pre‑market volatility models) as an upstream data source.

### 3. Risk Engineering Domain
- No risk‑limit, position‑sizing, or monitoring features are present in this repo.
- Risk engineering can utilize the pre‑market data for pre‑trade risk checks (e.g., verifying that pre‑market prices are within expected bands) but such logic would reside in eqats’ risk modules, not in this repository.

## Implementation Steps
1. Fork or clone `QuantMechanics/nse-premarket-data` into the eqats monorepo under `engines/data/nse_premarket`.
2. Refactor `index.js` to export a function `fetchPremarketData(options)` that returns a Promise resolving to the data payload.
3. Create an eqats wrapper service (`nsePremarketEngine.js`) that calls the function, logs results, and writes to the storage layer via eqats’ data‑access API.
4. Register a scheduled job in eqats’ job‑manager (e.g., using `node-cron` or the platform’s native scheduler) to run the wrapper at the desired cadence.
5. Write unit tests that mock the HTTP request to ensure reliable ingestion.
6. Document the new data source in eqats’ data‑catalog and update any relevant strategy documentation to reference the new pre‑market feed.

## Benefits
- Provides eqats with a reliable, low‑cost source of Indian NSE pre‑market quotes.
- Enables strategies that rely on early‑price discovery or gap‑opening signals.
- Minimal maintenance overhead due to the script’s simplicity.

## Caveats
- The script depends on the public NSE endpoint; any changes to NSE’s website or API may break the fetcher and require updates.
- No authentication or rate‑limiting is built‑in; consider adding headers or delays if needed for production use.