# Integration Blueprint: nsemodule → eqats

## Overview
nsemodule is a lightweight Python library that fetches real‑time market data from the National Stock Exchange (India). It provides APIs for live quotes, index data, top gainers/losers, and symbol validation. In the eqats quantitative trading platform, this library can serve as a **Data Engine** for Indian equity market data.

## Proposed Integration

### 1. Data Ingestion Layer
- Replace or supplement existing market‑data adapters with a thin wrapper around `nsemodule`.
- Expose the following endpoints to eqats’ data pipeline:
  - `get_live_quote(symbol)` → JSON with last price, bid/ask, volume, timestamp.
  - `get_bulk_quotes([symbol1, symbol2, ...])` → array of quote objects.
  - `get_index_quote(index_name)` → e.g., NIFTY 50, BANK NIFTY.
  - `get_top_gainers(limit=10)` and `get_top_losers(limit=10)`.
  - `is_valid_symbol(symbol)` for pre‑trade sanity checks.

### 2. Normalisation & Storage
- Map nsemodule’s JSON output to eqats’ canonical market‑data schema (timestamp, symbol, exchange, price, volume, etc.).
- Store raw JSON in a time‑series store (e.g., InfluxDB) for audit and back‑testing.
- Publish normalized ticks to eqats’ message bus (Kafka/Pulsar) for downstream consumers.

### 3. Usage in Signal & Execution Logic
- Strategies can subscribe to the live‑quote stream to compute technical indicators (e.g., VWAP, momentum) on Indian stocks.
- The symbol‑validation helper can be used in pre‑trade risk checks to reject orders for ill‑formed or delisted tickers.
- Top gainers/losers feeds can drive sector‑rotation or momentum‑based signals.

### 4. Risk Engineering Considerations
- Although nsemodule does not provide risk limits, the ingested data can feed eqats’ risk engine:
  - Real‑time price feeds for mark‑to‑market calculations.
  - Volume data for liquidity‑adjusted position sizing.
  - Symbol validation prevents erroneous orders that could breach risk limits.

### 5. Deployment & Maintenance
- Add `nsemodule` to eqats’ `requirements.txt` (or poetry/pipenv).
- Implement a thin adapter class (`NseMarketDataAdapter`) that handles rate‑limiting and retries per NSE’s usage policy.
- Unit‑test the adapter using mocked responses; integration test against a sandbox NSE endpoint if available.
- Monitor latency and error rates via eqats’ observability stack (Prometheus + Grafana).

## Benefits
- Immediate access to authoritative NSE real‑time data without building a custom scraper.
- Simple JSON output reduces parsing complexity.
- Helper APIs improve data quality upstream of signal generation and risk checks.

## Limitations
- Data accuracy depends on NSE’s public website; may be subject to delays or intermittent availability.
- No built‑in support for historical data retrieval; eqats would need a separate source for back‑testing.
- No authentication or API key required, but users must respect NSE’s terms of service.

## Conclusion
Integrating nsemodule as a dedicated Data Engine equips eqats with reliable, low‑latency Indian equity market data, enabling strategy development, execution, and risk management for NSE‑listed securities while keeping the implementation straightforward and maintainable.