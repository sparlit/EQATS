# Integration Blueprint: nse-bse-api with eqats

## Overview
The `nse-bse-api` package provides a unified TypeScript client for accessing real-time and historical market data from India's National Stock Exchange (NSE) and Bombay Stock Exchange (BSE). It offers endpoints for quotes, historical prices, option chains, corporate actions, announcements, market status, and more. This blueprint outlines how to leverage these data capabilities within the eqats quantitative trading platform, focusing on the Data Engines domain.

## Data Engines Integration
### Market Data Ingestion
- **Real‑time Quotes**: Use `nse.equityQuote(symbol)` and `bse.quote(scripcode)` to stream live prices into eqats' market data feed.
- **Historical Data**: Call `nse.historical.fetchEquityHistoricalData({symbol, from_date, to_date})` and `bse.historical` (if available) to backfill eqats' time‑series database.
- **Option Chain**: Retrieve full option chains via `nse.options.getOptionChain(symbol)` for volatility surface construction.
- **Symbol Lookup & Search**: Utilize `nse.market.lookup(query)` and `bse.lookupSymbol(text)` to maintain an up‑to‑date instrument master.
- **Corporate Actions & Announcements**: Pull dividends, splits, bonuses, and news via `nse.corporate.getActions(params)`, `nse.corporate.getAnnouncements(params)`, and BSE equivalents to adjust prices and feed event‑driven signals.
- **Market Status & Trading Hours**: Monitor `nse.market.getStatus()` and `bse.marketStatus()` to gate data collection and strategy execution.
- **Data Downloads (Bhavcopy, Reports)**: Schedule periodic downloads of bhavcopy and delivery reports for audit and compliance.

### Storage & Processing
- Store raw JSON responses in eqats' raw data lake (e.g., S3 or HDFS) partitioned by exchange, date, and data type.
- Transform to canonical eqats schema (timestamp, symbol, open, high, low, close, volume, etc.) using a lightweight TypeScript transformer service.
- Persist processed tick and bar data in eqats' timeseries store (e.g., TimescaleDB, kdb+, or InfluxDB) for low‑latency retrieval by strategies.
- Maintain corporate action adjustments in a reference table to adjust historical prices on‑the‑fly.

### Implementation Steps
1. **Add Dependency**: `npm install nse-bse-api` in the eqats data‑engine service.
2. **Initialize Clients**: Create singleton NSE and BSE clients with appropriate timeout and download folder config.
3. **Ingestion Workers**:
   - Quote worker: subscribe to a list of symbols, call `equityQuote`/`quote` at a configurable interval (e.g., 1 s) and publish ticks to eqats' message bus (Kafka/Pulsar).
   - Historical backfill worker: on startup, fetch missing historical bars for each symbol and write to the timeseries DB.
   - Option chain worker: run at market open to capture full chain and update volatility surface.
   - Corporate action worker: poll actions/announcements daily and apply adjustments.
4. **Error Handling & Retry**: Wrap API calls in try/catch, implement exponential backoff, and log failures to eqats' monitoring system.
5. **Configuration**: Expose timeout, download folder, and symbol lists via eqats' config service (YAML/JSON).
6. **Testing**: Use mock data or the package's error‑handling examples to unit test ingestion logic; run integration tests against a sandbox endpoint if available.
7. **Deployment**: Containerize the ingestion service (Docker) and deploy to eqats' Kubernetes cluster, scaling workers based on symbol count.

## Signal & Execution Logic
The `nse-bse-api` repository focuses solely on market data provision and does not include signal generation, strategy logic, or order execution capabilities. Consequently, no direct features map to the Signal & Execution Logic domain. Eqats would consume the data supplied by this API in its existing signal/research and execution modules.

## Risk Engineering
Similarly, the package does not provide risk‑limit calculations, position sizing tools, or real‑time risk monitoring. Risk‑related features would need to be implemented within eqats' risk engine using the market data obtained from this API.

## Summary
By integrating `nse-bse-api` as a market data ingestion layer, eqats gains reliable, low‑latency access to NSE and BSE equities, derivatives, and corporate‑action data. This enriches the Data Engines domain, enabling more accurate backtesting, live trading, and event‑driven strategies while keeping signal generation, execution, and risk management within eqats' existing components.
