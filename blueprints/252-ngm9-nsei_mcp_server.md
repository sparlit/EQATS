# Integration Blueprint: nsei_mcp_server → eqats

## Overview
The `nsei_mcp_server` is a Python‑based Model Context Protocol (MCP) server that exposes National Stock Exchange of India (NSEI) market data via a standardized interface. Its core capabilities are:
- **Get top movers** – retrieve gainers and losers for a user‑specified period (currently limited to ≤3 months).
- **Get latest trades** – stream the most recent trades for intraday analysis.

These features sit squarely in the **Data Engines** domain, providing clean, timely market data that eqats can ingest for downstream signal generation, execution, and risk monitoring.

## Mapping to eqats Domains

### Data Engines
| Feature | Description | eqats Integration Point |
|---------|-------------|------------------------|
| Top movers (gainers/losers) | Query NSEI for the biggest percentage gainers/losers over a configurable look‑back window. | Feed into eqats’ **market data engine** as a reference universe for screening, sector rotation, or alpha‑model inputs. |
| Latest trades | Retrieve real‑time trade ticks (price, size, timestamp) for any listed security. | Supply eqats’ **tick‑data handler** to build VWAP, order‑flow imbalance, or microprice features used by signal modules. |
| Planned caching | Future implementation will cache responses with log rotation (10 MB files, 5 backups). | Reduce redundant API calls to FMP/NSEI, lowering latency and cost when eqats repeatedly queries the same symbols or time windows. |

### Signal & Execution Logic
The server does **not** contain any signal generation, strategy logic, or order‑execution code. Its value to eqats lies in providing the raw data that eqats’ existing signal & execution components already expect:
- **Signal generation**: Use top‑movers lists as a universe for momentum or mean‑reversion strategies; use latest trades to compute short‑term momentum, volume‑weighted averages, or order‑flow signals.
- **Execution**: Feed latest trade prices into eqats’ execution algorithms (e.g., TWAP, VWAP) to improve slippage estimates.

Integration is therefore a matter of configuring eqats’ data adapters to call the MCP endpoints (via stdio or network) and map the returned JSON payloads to eqats’ internal market‑data structures.

### Risk Engineering
No explicit risk limits, position‑sizing, or risk‑monitoring features are present. However, the data supplied can be consumed by eqats’ risk engine:
- **Real‑time risk monitoring**: Latest trades enable real‑time mark‑to‑market and liquidity‑risk calculations.
- **Limit checking**: Top‑movers data can trigger alerts when a security breaches predefined movement thresholds, prompting risk‑team review.
- **Exposure analysis**: Aggregating top‑mover lists across sectors helps eqats gauge sector‑concentration risk.

Thus, while the server does not implement risk logic, it enriches eqats’ risk‑engine data feed.

## Implementation Steps
1. **Expose MCP Endpoints** – Ensure the `nsei_mcp_server` is running and accessible (stdio or TCP) from the eqats host.
2. **Create eqats Data Adapter** – Write a thin wrapper that:
   - Sends MCP `get_top_movers` and `get_latest_trades` requests.
   - Parses the JSON responses into eqats’ `MarketSnapshot` and `TradeTick` objects.
   - Handles errors, retries, and respects the server’s rate limits (guided by the FMP API key usage).
3. **Integrate with Engines** – Register the adapter as a data source in eqats’ market‑data engine, specifying refresh intervals (e.g., top movers every 15 min, latest trades streaming).
4. **Leverage Caching (when available)** – Once caching is deployed, configure the adapter to benefit from reduced latency for repeated queries.
5. **Risk‑Engine Hooks** – Feed the incoming data into eqats’ risk‑monitoring modules to compute real‑time VaR, liquidity scores, and breach alerts.
6. **Testing & Validation** – Validate that data latency and completeness meet eqats’ operational SLAs before promoting to production.

## Benefits
- **Standardized Access**: MCP provides a uniform, language‑agnostic interface, simplifying future swaps of data providers.
- **Focused Data**: The server delivers exactly the two high‑value datasets eqats needs for many alpha and risk models.
- **Low Overhead**: Minimal code changes; the adapter is a thin translation layer.

## Caveats
- The server currently depends on an external Financial Modeling Prep (FMP) API key; ensure eqats’ deployment includes secure key management.
- No built‑in handling of corporate actions or fundamentals; eqats must supplement with other sources if required.
- Caching and log rotation are planned but not yet implemented; monitor for future updates.

By integrating `nsei_mcp_server` as a dedicated market‑data feed, eqats gains reliable, real‑time NSEI intelligence that can directly power its signal generation, execution, and risk‑monitoring workflows without reinventing data‑acquisition logic.