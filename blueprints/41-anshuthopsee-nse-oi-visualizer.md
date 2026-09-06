# Integration Blueprint for eqats: nse-oi-visualizer

## Overview
The nse-oi-visualizer provides a real‑time Open Interest (OI) visualizer and strategy builder for Indian equity derivatives. Its core strengths lie in market‑data ingestion, IV computation, and interactive strategy payoff visualization. These capabilities can be leveraged to enhance eqats’ data engine, signal generation, and risk monitoring layers.

## Data Engine Enhancements
- **Real‑time OI Feed**: Replicate the NSE API polling mechanism (web‑worker triggered at minutes divisible by 3) to stream OI and change‑in‑OI for indices and F&O stocks into eqats’ market‑data store.
- **Caching Layer**: Adopt RTK Query‑style caching with a 3‑minute TTL to reduce redundant API calls while keeping data fresh.
- **Persistence**: Store user‑selected underlying symbols in localStorage (or eqats’ user‑preferences service) to restore state on reload.
- **Synthetic Futures Price**: Implement the put‑call parity based synthetic futures calculation as a derived field in the market‑data pipeline, enabling consistent IV inputs across expiries.

## Signal & Execution Logic Additions
- **IV Engine**: Integrate the Black‑76 IV calculator (already ported from the referenced Python repo) to compute implied volatility for each strike; expose OTM call/put IV as signals.
- **Strategy Builder**: Reuse the multi‑expiry and strike‑range selectors to let users construct option legs (up to 10) and instantly view payoff curves at target date and expiry.
- **Payoff Visualization**: Plug the D3‑based payoff line chart into eqats’ dashboard, providing tooltips and interactive strike adjustment.
- **Signal Generation**: Derive trading signals from OI‑change patterns (e.g., sudden OI buildup) combined with IV extremes, feeding into eqats’ signal engine.

## Risk Engineering Considerations
- While the source repo lacks explicit risk limits, the OI‑change and IV metrics can be fed into eqats’ risk monitors to flag abnormal OI concentration or volatility spikes.
- Future work: add position‑sizing checks based on margin‑impact derived from strategy payoff, and implement error boundaries for robust UI.

## Implementation Steps
1. **Backend Service**: Create a Node.js micro‑service that mirrors the NSE API fetcher, web‑worker scheduler, and RTK Query cache.
2. **Data Model**: Extend eqats’ market‑data schema with OI, change‑in‑OI, synthetic futures, and IV fields.
3. **Frontend Components**: Import the React/MUI strategy‑builder UI (strike selector, expiry multi‑select, payoff chart) into eqats’ strategy module.
4. **Utility Library**: Publish the Black‑76 IV and put‑call parity functions as a shared npm package for both backend and frontend.
5. **Testing**: Write unit tests for IV calculations and integration tests for the auto‑update loop.

## Expected Outcome
By incorporating these features, eqats will gain a robust, low‑latency OI data pipeline, an interactive multi‑leg strategy payoff tool, and a foundation for volatility‑driven signal generation—enhancing both analytical depth and user experience.