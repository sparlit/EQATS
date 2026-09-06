# ShareWatch Integration Blueprint for eqats

## Overview
ShareWatch is a Node.js/JavaScript library that provides real-time and historical market data for Indian exchanges (NSE and BSE). It offers programmatic APIs and a CLI to retrieve equity lists, indices, quotes, and bhavcopy files.

## Relevant Features for eqats
- **Data Ingestion**: 
  - `NSE.equityList()` / `BSE.equityList()` – retrieve full list of securities with ISIN, scrip code, etc.
  - `NSE.indices()` / `BSE.indices()` – real‑time index values (NIFTY50, BSE Sensex, etc.).
  - `NSE.quote(symbol)` / `BSE.quote(scripCode)` – live price for a single equity.
  - `BSE.quoteWithComparison(scripCode)` – quote plus peer comparison.
  - `NSE.bhavcopy(date)` / `BSE.bhavcopy(date)` – end‑of‑day bhavcopy (trade‑by‑trade or OHLCV) for a given date.
  - CLI equivalents (`sharewatch -p nse equity-list`, etc.) for scripting and automation.

## How to Integrate into eqats
1. **Wrap ShareWatch as a Data Engine Service**
   - Create a thin adapter (`sharewatchAdapter.js`) that exposes a uniform interface matching eqats’ data‑engine contract (e.g., `getEquityList(exchange)`, `getIndexData(exchange)`, `getQuote(exchange, identifier)`, `getHistoricalData(exchange, date)`).
   - The adapter returns normalized JSON objects (symbol, timestamp, price, volume, etc.) that eqats’ downstream components expect.

2. **Data Pipeline**
   - Use the adapter in eqats’ ingestion layer to populate a real‑time cache (e.g., Redis) and a historical store (e.g., TimescaleDB) for NSE/BSE instruments.
   - Schedule periodic bhavcopy pulls (daily) to enrich the historical database.

3. **Signal & Execution Logic**
   - While ShareWatch does not generate signals, the cleaned market data can feed eqats’ strategy modules.
   - Example: a moving‑average crossover strategy can subscribe to the real‑time quote stream from the adapter.
   - Execution adapters (e.g., broker APIs) remain unchanged; ShareWatch solely supplies the market data feed.

4. **Risk Engineering**
   - Real‑time price and volume data from ShareWatch enable risk‑monitoring checks (e.g., price‑change limits, liquidity thresholds) within eqats’ risk engine.
   - Historical bhavcopy data supports value‑at‑risk (VaR) calculations and stress‑testing for Indian equities.

## Benefits
- Immediate access to authoritative NSE/BSE data without building custom scrapers.
- CLI support allows quick ad‑hoc data checks during strategy development.
- Well‑maintained npm package (`sharewatch`) with Node.js v6.11+ compatibility.

## Considerations
- ShareWatch relies on public NSE/BSE endpoints; monitor for rate limits or API changes.
- For high‑frequency trading, consider co‑locating the adapter or using a websocket‑based feed if ShareWatch introduces latency.
- Ensure data timestamps are normalized to UTC for consistency with eqats’ internal clock.

## Summary
By integrating ShareWatch as a dedicated data‑engine module, eqats gains reliable, real‑time and end‑of‑day Indian market data, enabling strategy research, backtesting, live trading, and risk monitoring for NSE and BSE securities.