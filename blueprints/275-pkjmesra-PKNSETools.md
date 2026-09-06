# Integration Blueprint for PKNSETools into eqats

## Overview
PKNSETools is a Python library focused on fetching Indian NSE and NASDAQ market data. It provides robust data ingestion capabilities that can be leveraged as the data engine layer within the eqats quantitative trading platform.

## Proposed Integration

### 1. Data Engine Layer
- Replace or augment eqats' current market data adapters with the `nseStockDataFetcher` class.
- Use its automatic source selection (PKBrokers → NSE API → yfinance) to ensure high‑availability data for Indian equities.
- Expose the fetcher through eqats' `DataEngine` interface: implement methods `fetch_ohlcv(symbol, timeframe, limit)` and `fetch_latest_tick(symbol)` that delegate to `fetchStockData` with appropriate `period` and `interval` arguments.
- Leverage the `fetchStockCodes` method to dynamically populate eqats' universe for Nifty indices (passing index codes 1, 2, 3, …) and the full equity list (code 12).
- Incorporate the NASDAQ index module (`PKNasdaqIndex`) to extend eqats' coverage to US indices when needed.
- Use the Morningstar tools module to enrich fundamental data (fair value, ratings) for risk‑adjusted signal generation.

### 2. Real‑Time Intraday Integration
- During market hours, configure the fetcher to use the PKBrokers source (as shown in the architecture diagram) for low‑latency tick data.
- Map the fetched intraday DataFrames to eqats' internal bar format and publish to the signal engine via the existing event bus.

### 3. Historical Data & Backtesting
- The historical data module (up to 3 years) can feed eqats' backtesting harness.
- Provide a helper that converts the returned OHLCV DataFrame to the format expected by eqats' `Backtester` (timestamp, open, high, low, close, volume).

### 4. Configuration & Extensibility
- Add a new eqats configuration section `data_sources.pknsetools` with parameters: `download_folder`, `preferred_source` (PKBrokers, NSE, yfinance), `cache_enabled`.
- Implement a factory that instantiates the appropriate underlying source based on the config, mirroring the auto‑selection logic already present in `nseStockDataFetcher`.

### 5. Testing & Validation
- Write unit tests that mock the NSE API responses to verify eqats receives correctly formatted data.
- Run end‑to‑end tests during market hours to confirm real‑time data flow from PKBrokers through eqats to the signal engine.

## Benefits
- **Unified access**: Single interface for multiple data sources reduces fragility.
- **Extended coverage**: Adds Indian equities and NASDAQ indices to eqats' universe.
- **Fundamental enrichment**: Morningstar data enables value‑oriented signals.
- **Performance**: Optional PKBrokers integration provides low‑latency intraday feeds.

## Domain Mapping
- **Data Engines**: All features listed above (ingestion, multiple sources, real‑time, historical, fundamentals).
- **Signal & Execution Logic**: None – PKNSETools does not generate signals or execute orders.
- **Risk Engineering**: None – the library does not compute risk limits, position sizing, or monitoring.

---
*This blueprint is derived strictly from the README of pkjmesra/PKNSETools; no capabilities beyond those documented are assumed.*