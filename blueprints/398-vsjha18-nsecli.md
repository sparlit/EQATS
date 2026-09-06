# Integration Blueprint: NSE CLI Data Engine for eqats

## Overview
The vsjha18/nsecli repository provides a command‑line tool for fetching live National Stock Exchange (NSE) equity quotes with a fuzzy‑search front‑end. The core valuable feature is the low‑latency retrieval of real‑time prices via NSE’s public JSON endpoint.

## Domain Mapping
- **Data Engines**: Live quote retrieval, HTTP client with caching, fuzzy symbol matching.
- **Signal & Execution Logic**: Not directly supplied; the quote stream would feed eqats’ signal generators.
- **Risk Engineering**: Not applicable; risk modules would consume the price data for valuation, VaR, etc.

## Proposed Integration
1. Extract the HTTP request logic from nsecli into a Rust function get_nse_quote(symbol: &str) -> Result<f64, Err>.
2. Expose the function to Python via PyO3, enabling eqats strategies to call it directly.
3. Add a optional fuzzy‑search wrapper that loads the NSE symbol list and matches user input.

## Challenges & Infeasibility
- NSE’s public endpoints require specific headers (User‑Agent, Referer) and often rely on session cookies that change frequently.
- Automated scraping may breach NSE’s terms of service; the official data feed is subscription‑based.
- Maintaining reliable access would need continuous reverse‑engineering, which is outside the scope of a stable quant platform.
- Consequently, a direct integration of the nsecli approach is deemed infeasible for production use in eqats.

## Alternative Path
Use a licensed market data provider (e.g., NSE’s official API, Bloomberg, or Reuters) or a delayed free source (e.g., Yahoo Finance) with proper compliance.

## Conclusion
While the nsecli demonstrates a useful pattern for fast equity look‑ups, integrating it directly into eqats is not recommended due to legal and reliability concerns. The blueprint documents the intended design for reference should a compliant data source become available.