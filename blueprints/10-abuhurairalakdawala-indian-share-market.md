# Integration Blueprint for eqats: Indian Share Market Data Provider

## Repository Overview
- Name: abuhurairalakdawala/indian-share-market
- Language: PHP
- Purpose: Provides real-time and reference data from NSE and BSE (stocks, sectors, industries, quotes).
- Current Features:
  - Latest stock quotes (NSE & BSE)
  - Sector and industry lists
  - Real-time stock quotes
- Planned Features (per TODOs):
  - Top Gainers / Losers
  - Futures & Options data
  - Historical data

## How It Fits into eqats
equats separates concerns into three domains:
1. Data Engines – ingestion, storage, and serving of market data.
2. Signal & Execution Logic – strategy signals, order generation, execution.
3. Risk Engineering – risk limits, position sizing, monitoring.

### Data Engines Integration
The PHP library can be wrapped as a data‑engine plugin for eqats:
- Use Composer to depend on `abuhurairalakdawala/indian-share-market`.
- Implement an adapter that calls the library’s methods (getLatestStocks, getSectors, getIndustries, getRealTimeQuote) and maps the returned JSON/CSV/Array to eqats’ canonical market‑data format (e.g., internal Tick or Bar objects).
- Schedule periodic pulls (via cron or eqats’ scheduler) to keep a local cache (Redis/TimescaleDB) of the latest quotes and reference data.
- When the planned features are released, extend the adapter to fetch top gainers/losers, futures/options chains, and historical bars, feeding them into eqats’ historical‑data store.

### Signal & Execution Logic
The repository does not contain any signal generation or order‑execution code. Consequently:
- Strategies in eqats would consume the market data supplied by this adapter.
- Signal generation (e.g., moving‑average crossovers, breakout detectors) and order execution (via broker APIs) remain the responsibility of eqats’ strategy engine.
- No changes are needed in this domain; the data engine simply feeds the required inputs.

### Risk Engineering
Similarly, no risk‑management features are present. Risk calculations (VaR, position limits, margin checks) would be performed in eqats’ risk engine using the data provided by this adapter.
- Ensure that the adapter supplies timestamps and data quality flags so the risk engine can detect stale or missing data.
- If real‑time quotes are needed for intraday risk limits, configure the adapter to push updates via a websocket or polling mechanism.

## Implementation Steps
1. Add Dependency
   ```bash
   composer require abuhurairalakdawala/indian-share-market
   ```
2. Create Adapter (eqats/data/engines/IndianShareMarket.php)
   - Wrap library calls.
   - Normalize output to eqats’ internal data structures.
   - Handle errors and retries.
3. Register Adapter in eqats’ data‑engine configuration.
4. Set Up Ingestion Schedule (e.g., every 5 seconds for quotes, daily for reference lists).
5. Persist Data to eqats’ storage layer (e.g., TimescaleDB for ticks, Redis for latest quotes).
6. Extend Adapter when the library adds top gainers/losers, futures/options, and historical data.
7. Validate integration by running eqats’ unit tests that mock the adapter and verify downstream signal/risk components receive correct data.

## Benefits
- Immediate access to Indian‑exchange data without building scrapers.
- Leverages a well‑maintained, MIT‑licensed PHP package.
- Enables eqats to expand its coverage to Indian markets with minimal effort.

## Limitations & Considerations
- The library is PHP‑only; eqats may be primarily in another language (e.g., Python/Java). In that case, consider running a lightweight PHP micro‑service or using the library via a REST wrapper (the repo mentions REST API support).
- Real‑time frequency depends on the library’s polling of the exchanges; verify latency meets your strategy requirements.
- No built‑in error handling for exchange downtime; the adapter should implement circuit‑breaker logic.

## Conclusion
By wrapping abuhurairalakdawala/indian-share-market as a data‑engine plugin, eqats can quickly ingest NSE/BSE market data, enabling strategy development, backtesting, and live trading for Indian equities while keeping signal/execution and risk layers unchanged.