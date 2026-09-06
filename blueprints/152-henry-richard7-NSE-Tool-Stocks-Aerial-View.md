# Integration Blueprint for NSE-Tool-Stocks-Aerial-View into eqats

## Overview
The NSE-Tool-Stocks-Aerial-View repository provides a C#‑based desktop application that scrapes live National Stock Exchange (NSE) data and computes common technical indicators: Pivot points, Resistance levels, and Displaced Moving Average (DMA) for multiple look‑back periods. It also offers summary views for stocks within an index and for indices themselves.

While the tool does not contain signal generation, order execution, or risk‑management logic, its data‑engine capabilities are valuable for eqats as a source of real‑time market data and pre‑computed technical indicators.

## Proposed Integration

### 1. Data Engine Module
- **Create a new eqats data‑engine plugin** (e.g., `eqats-nse-tool`) that wraps the existing C# scraping logic.
- Expose the core functions via a thin REST/gRPC service or as a .NET assembly that can be called from eqats’ Python/Java‑based pipeline using interop (e.g., `pythonnet` or `grpc`).
- The plugin should provide the following endpoints:
  - `GET /live-price/{symbol}` – returns the latest scraped price.
  - `GET /pivot/{symbol}` – returns pivot, support, and resistance levels.
  - `GET /dma/{symbol}?period={20|50|100|150|200}` – returns the DMA value for the requested period.
  - `GET /summary/index/{indexName}` – returns summary statistics for all stocks in the given index.
  - `GET /summary/indices` – returns summary for all available indices.
- Cache results appropriately (e.g., in-memory TTL of 5‑10 seconds) to reduce load on the NSE website.
- Ensure error handling and retry logic for network/scraping failures.

### 2. Consumption in eqats
- **Market Data Feed**: Register the NSE‑Tool plugin as an additional market‑data source alongside existing feeds (e.g., Kafka, WebSocket). eqats’ data‑engine layer can subscribe to the plugin’s endpoints and normalize the output into its internal tick format.
- **Feature Enrichment**: Use the DMA and pivot/resistance values as pre‑computed technical features for downstream signal generation. These can be joined with other asset data (e.g., fundamentals, alternative data) in eqats’ feature store.
- **Index Summaries**: Leverage the index‑summary endpoints to populate eqats’ universe‑selection logic, enabling dynamic filtering based on index‑wide metrics.

### 3. Deployment & Maintenance
- Package the C# application as a Docker container (using `mcr.microsoft.com/dotnet/framework/sdk` runtime) to simplify deployment within eqats’ Kubernetes‑based infrastructure.
- Provide a Helm chart that defines the service, resource limits, readiness/liveness probes, and config maps for symbols/indices to track.
- Set up monitoring (Prometheus metrics) for scrape latency and success rates.
- Schedule periodic updates to the underlying scraping logic if the NSE website structure changes.

### 4. Limitations & Considerations
- The tool is primarily a Windows‑Forms desktop app; extracting the core scraping/calculation logic into a library may require refactoring.
- Legal/ethical scraping: ensure compliance with NSE’s terms of use and consider using official data feeds where possible.
- No built-in rate‑limiting; the plugin should implement polite request throttling.

## Conclusion
By isolating the data‑acquisition and indicator‑calculation components of NSE‑Tool-Stocks-Aerial-View and exposing them as a service, eqats gains a reliable source of real‑time NSE prices and widely used technical indicators (pivot, resistance, DMA). This enriches eqats’ data‑engine layer without duplicating effort, while signal execution and risk‑management responsibilities remain within eqats’ existing modules.
