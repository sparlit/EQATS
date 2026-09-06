# Integration Blueprint: Chartink-to-TradingView Extension into eqats

## Overview
The Chartink-to-TradingView extension is a lightweight WebExtension that rewrites URLs in Chartink scanner results to open corresponding TradingView charts. Its core functionality is URL parsing and redirection based on extracted stock symbols.

## Feature Mapping to eqats Domains
- **Data Engines**: Symbol extraction and URL construction – can be reused as a pre‑processing step that enriches raw screening data with chart links.
- **Signal & Execution Logic**: No direct signal generation or order execution capabilities.
- **Risk Engineering**: No risk‑limiting or position‑sizing features.

## Integration Points (Data Engines)
1. **Ingestion Adapter** – Replace the client‑side extension with a server‑side micro‑service (Node.js/Python) that:
   - fetches Chartink scanner result pages (via HTTP GET or headless browser),
   - parses the HTML to collect ticker symbols (NSE stocks),
   - builds TradingView chart URLs using the pattern `https://www.tradingview.com/chart/?symbol=NSE:<SYMBOL>`,
   - stores the symbol‑to‑chart mapping alongside the raw scanner data in eqats’ data lake or feature store.
2. **Enrichment Layer** – When eqats generates a signal from a screened symbol, lookup the pre‑computed TradingView URL and attach it to the signal payload for UI visualization.
3. **API Endpoint** – Expose a REST/GraphQL endpoint (`/api/chartink/charts`) that returns the mapping for a list of symbols, enabling the front‑end to launch TradingView charts directly from eqats’ dashboard.

## Implementation Steps
1. **Extract Core Logic** – Isolate the URL‑building function from the extension’s `content.js`/`background.js`.
2. **Create Adapter Service** – Write a lightweight service (e.g., Express.js) that implements the extraction logic server‑side.
3. **Add Caching** – Cache symbol‑to‑chart mappings for a configurable TTL to reduce repeated Chartink requests.
4. **Integrate with eqats Pipeline** – Hook the adapter into eqats’ data ingestion stage (e.g., as a Kafka connector or Airflow operator).
5. **Update UI** – Modify eqats’ dashboard to consume the chart URL field and render a “Open in TradingView” button next to each signal.
6. **Testing & Monitoring** – Validate against known Chartink scanner outputs, monitor latency, and add alerts for failed fetches.

## Potential Benefits
- Seamless transition from eqats’ signal generation to interactive chart analysis without manual symbol entry.
- Centralized chart‑link management, ensuring consistency across multiple strategies.
- Reduced client‑side complexity; the logic lives in the eqats backend, accessible to all interfaces (web, mobile, API).

## Considerations
- The extension currently works only for NSE stocks; ensure any symbol mapping respects this limitation.
- Chartink’s HTML structure may change; implement robust selectors and fallback mechanisms.
- Respect Chartink’s terms of service and rate‑limit when polling scanner pages.