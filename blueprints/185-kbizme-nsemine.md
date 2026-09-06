# Integrating `nsemine` into the eqats Quantitative Trading Platform

## Overview
`nsemine` is a lightweight, asynchronous Python library for scraping real‑time and historical data from the National Stock Exchange of India (NSE) and Nifty Indices. It provides ready‑to‑use functions for live quotes, historical price series, and futures/options data, backed by caching and robust error handling. In the eqats architecture, `nsemine` fits squarely into the **Data Engines** layer, supplying clean market data that downstream signal‑generation, execution, and risk‑management components can consume.

## Proposed Integration Points

### 1. Data Engine Wrapper
Create a thin adapter in eqats that exposes the nsemine API as a uniform data‑feed interface (e.g., `eqats.data.nse.NSEFeed`).
- **Live Feed**: Use `live.get_stock_live_quotes`, `live.get_index_live_price`, and `live.get_fno_live_data` (once the fno module matures) inside an asyncio task loop.
- **Historical Feed**: Wrap `historical.get_stock_historical_data` and `historical.get_index_historical_data` for back‑testing and batch data loads.
- **Caching Leverage**: nsemine’s built‑in TTL‑based cache reduces redundant HTTP calls; configure the cache size/ttl to match eqats’ subscription rates.
- **Raw vs Processed Data**: Offer both raw JSON (for low‑level debugging) and processed pandas DataFrames (for immediate vectorized analysis) via the adapter’s `raw` flag.

### 2. Async Data Pipeline
- Integrate the adapter into eqats’ existing async data‑pipeline (likely built on `asyncio` or `trio`).
- Each subscribed instrument spawns a coroutine that calls the appropriate nsemine live function at a configurable interval (e.g., 1 s for liquid stocks, 5 s for indices).
- Errors returned by nsemine (e.g., `None` on failure) are translated into eqats’ standard `DataFeedError` and trigger retry/back‑off logic.

### 3. Feature Engineering & Signal Generation
- The processed DataFrames from nsemine feed directly into eqats’ feature‑engineering modules (e.g., VWAP, momentum, volatility).
- Because nsemine already returns numpy‑friendly arrays, vectorized signal calculations can be performed without extra conversion.
- Futures/options data from the `fno` module (once stable) can be used to build term‑structure, skew, and open‑interest based signals.

### 4. Risk Engineering Consumption
- Real‑time price and volume streams are fed to eqats’ risk‑monitoring services to compute:
  - Intraday VaR / volatility estimates.
  - Margin utilization for futures/options positions.
  - Liquidity‑adjusted position limits using nsemine’s volume and depth data.
- Historical data supports end‑of‑day risk reports, stress‑testing, and back‑testing of risk limits.

### 5. Deployment & Configuration
- Add `nsemine` to eqats’ `requirements.txt` or `pyproject.toml`.
- Provide a YAML config block:
  ```yaml
  data_feeds:
    nse:
      enabled: true
      symbols:
        - TCS
        - INFY
        - NIFTY 50
      intervals:
        live: 1s
        historical: 1d
      cache_ttl: 60  # seconds
  ```
- The adapter reads this config, initializes nsemine with appropriate parameters, and registers the feed with eqats’ data‑manager.

## Benefits
- **Performance**: Asynchronous calls and caching keep latency low and reduce the chance of being blocked by NSE’s anti‑scraper mechanisms.
- **Simplicity**: Clean, well‑documented API reduces boilerplate; eqats developers can focus on strategy logic rather than data‑parsing.
- **Coverage**: Single library provides equities, indices, and (eventually) futures/options, eliminating the need for multiple data‑source adapters.
- **Reliability**: Built‑in exception handling and optional raw‑response fallback aid debugging and ensure pipeline stability.

## Limitations & Mitigations
- **No Direct Signal/Order Features**: nsemine supplies data only; signal generation and order execution must be implemented elsewhere in eqats (already the case).
- **Maturity Flag**: The repository warns of frequent updates; pin to a specific version or tag in eqats’ dependency lockfile to avoid breaking changes.
- **Data Scope Limited to NSE**: For global multi‑asset strategies, combine nsemine with other feeds (e.g., Bloomberg, Polygon) within eqats’ hybrid data‑engine framework.

## Conclusion
By wrapping `nsemine` as an asynchronous, cached data feed within eqats’ Data Engines layer, the platform gains fast, reliable access to Indian market data—essential for building, testing, and executing strategies that involve NSE listed securities, indices, and derivatives. The adapter’s design keeps the integration minimal, maintainable, and fully aligned with eqats’ existing async‑first architecture.