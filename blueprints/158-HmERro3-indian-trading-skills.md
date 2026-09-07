# Integration Blueprint for indian-trading-skills into eqats

## Overview
The indian-trading-skills repository provides modules for analyzing Indian equity markets, including NSE/BSE stocks, derivatives, market flows, news, and trade planning.

## Domain Mapping

### Data Engines
- **NSE/BSE Stock Data Ingestion**: Pull historical and real‑time equity prices.
- **Derivatives Data Ingestion**: Futures and options data from NSE/BSE.
- **Market Flows Ingestion**: Institutional flow data, bulk deals, etc.
- **News Data Ingestion**: Scrape news feeds for market-moving events.

These can be plugged into eqats' data engine layer to enrich the universal market data feed with India‑specific instruments.

### Signal & Execution Logic
- **Trade Planning Module**: Generates entry/exit ideas based on technical/fundamental cues.
- **Signal Generation**: Derive signals from combined price, flow, and news inputs.
- **Execution Logic**: Interface with broker APIs for order placement (to be adapted).

Integration steps:
1. Wrap each planning function as a signal producer compatible with eqats' signal bus.
2. Map trade planning outputs to eqats' order sizing and risk checks.
3. Use the execution adapter to route orders through eqats' execution engine.

### Risk Engineering
*No explicit risk‑management features are present in the repository.*
To add risk controls, eqats' existing risk engine can be applied:
- Position sizing based on volatility derived from the ingested data.
- Stop‑loss and take‑profit rules enforced by eqats' risk module.
- Monitoring of exposure limits per sector (e.g., banking, IT) using the news and flow data.

## Implementation Blueprint
1. **Data Layer**: Add a new `indian_market` provider in eqats/data_engines that calls the repository's ingestion functions.
2. **Signal Layer**: Create `indian_signal` plugins that consume the provider outputs and emit signals to eqats' signal bus.
3. **Execution Layer**: Extend eqats' execution adapter to accept trade‑plan objects from the repository and translate them into broker‑specific orders.
4. **Risk Layer**: Leverage eqats' built‑in risk checks; optionally add India‑specific risk rules (e.g., margin requirements for derivatives) as plugins.
5. **Testing**: Use the repository's sample notebooks to validate data fidelity and signal accuracy before live deployment.

## Expected Benefits
- Immediate access to India‑focused equity and derivatives data.
- Ready‑made trade‑planning ideas that can be refined within eqats' framework.
- Enhanced news‑driven signal generation for Indian markets.
- Minimal duplication of effort; risk management remains centralized in eqats.

## Open Items
- Define concrete API contracts between the repository's modules and eqats' interfaces.
- Implement authentication for NSE/BSE data sources (if required).
- Back‑test the trade‑planning logic across multiple market regimes.