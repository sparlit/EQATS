# Integration Blueprint: NseIndiaApi for eqats

## Overview
The NseIndiaApi repository provides an unofficial Python client for the National Stock Exchange (NSE) of India. It offers easy access to a variety of market data endpoints such as equity bhavcopy, delivery bhavcopy, advance‑decline ratios, market status, and corporate actions. The client handles session cookies, provides a configurable download folder for caching, and includes built‑in rate‑limit awareness (3 requests/second) with an optional HTTP/2 mode for server deployments.

## Mapping to eqats Domains

### Data Engines
- **Market Data Ingestion**: Wrap the `NSE` class as a data‑engine plugin (`NSEDataEngine`) that exposes methods like `get_equity_bhavcopy(date)`, `get_delivery_bhavcopy(date)`, `get_advance_decline()`, `get_market_status()`, `get_corporate_actions()`.
- **Caching & Persistence**: Utilize the `download_folder` argument to store cookies and downloaded CSV/JSON files, enabling eqats’ data‑engine to reuse previously fetched files and reduce redundant network calls.
- **Rate‑Limit Handling**: Leverage the library’s internal throttling (≈3 req/s) and the optional `server=True` mode (httpx with HTTP2) for high‑frequency or cloud‑based deployments (AWS, GCP). eqats can configure the engine to use the server mode when running in containerized environments.
- **Error Handling**: The plugin will catch exceptions raised by the NSE client (e.g., network errors, invalid dates) and translate them into eqats’ standard data‑engine error types, allowing retry logic or fallback to cached data.

### Signal & Execution Logic
- **Signal Generation**: The NSE India API does not create trading signals. Instead, eqats’ signal modules can consume the data frames returned by the engine (e.g., bhavcopy OHLCV, delivery quantities, advance‑decline breadth) to compute custom indicators, sentiment scores, or strategy‑specific filters for Indian equities.
- **Order Execution**: No direct order‑routing capability exists in this library. Execution would continue to be handled by eqats’ existing execution adapters (e.g., broker APIs). The NSE engine serves purely as a data source.

### Risk Engineering
- **Risk Metrics**: The API does not provide risk‑limit or position‑sizing features. Risk engineering in eqats would rely on the ingested market data (prices, volumes, corporate actions) to compute VaR, exposure limits, concentration checks, etc., using eqats’ risk‑engine components.
- **Monitoring**: Real‑time status and advance‑decline data can be fed into eqats’ risk‑monitoring dashboards to gauge market breadth and liquidity conditions for the Indian market.

## Implementation Steps
1. **Create a Wrapper** (`eqats/data_engines/nse_india.py`):
   - Initialize `NSE(download_folder=<eqats_cache_dir>, server=<use_httpx>)`.
   - Expose async/sync methods matching eqats’ data‑engine interface.
   - Implement `fetch_ohlcv(symbol, start, end)` by iterating over bhavcopy files.
   - Implement `get_market_breadth()` using `advanceDecline()`.
   - Implement `get_corporate_actions(symbol)` using `actions()`.

2. **Configure Rate Limits**:
   - Set `server=True` for deployments on AWS/Linux to enable HTTP2.
   - Optionally add a thin wrapper that sleeps 0.5‑1s between calls if extra safety is needed.

3. **Integrate with eqats’ Pipeline**:
   - Register the NSE engine in eqats’ data‑engine registry.
   - In signal‑generation workflows, pull the latest bhavcopy or breadth data as inputs.
   - In risk‑monitoring workflows, stream status and advance‑decline metrics.

4. **Testing & Validation**:
   - Use the provided `src/samples` folder to unit‑test the wrapper against known payloads.
   - Run integration tests against a live NSE endpoint during market hours, respecting the 3 req/s limit.

## Benefits
- **Native Indian Market Data**: Immediate access to authoritative NSE bhavcopy and corporate‑action feeds without scraping.
- **Built‑in Session Management**: Cookie handling and automatic reconnection reduce boilerplate.
- **Scalable Deployment**: HTTP2 support enables low‑latency, high‑throughput usage in cloud environments.
- **Leverages Existing eqats Infrastructure**: Plug‑in style integration keeps eqats’ core architecture unchanged.

## Caveats
- The library is unofficial; reliance on NSE’s public endpoints may break if NSE changes its web interface.
- No authentication is required, but excessive usage may lead to temporary IP bans; adhere to the documented rate limits.
- No direct order‑execution or risk‑limit features; these must be supplied by other eqats components.

## Conclusion
By wrapping NseIndiaApi as a dedicated data‑engine plugin, eqats gains a robust, maintenance‑light source of Indian equity market data. This enables strategy development, backtesting, and live trading on the NSE while keeping signal generation, execution, and risk management within eqats’ established frameworks.