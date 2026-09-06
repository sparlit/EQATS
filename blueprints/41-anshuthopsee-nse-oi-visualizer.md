# Integration Blueprint: nse-oi-visualizer → eqats

## Overview
The `nse-oi-visualizer` repository provides a real‑time Open Interest (OI) and option‑strategy payoff visualizer for Indian benchmark indices and F&O stocks. Built with TypeScript, React, Material UI, D3, Redux, RTK Query, and a Node.js backend, it demonstrates robust market‑data ingestion, caching, and analytics that can be leveraged within the eqats quantitative‑trading platform.

## Data Engines – Reusable Features

### 1. Market‑Data Ingestion
- **NSE API Wrapper**: The backend fetches OI, change in OI, and option chain data for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, and 185 F&O stocks.
- **Web‑Worker Scheduler**: Data refresh is triggered exactly when minutes are divisible by 3 (e.g., 9:30, 9:33, …) using a web worker, ensuring low‑latency updates without blocking the UI.
- **RTK Query Caching**: Responses are cached with a maximum age of 3 minutes, reducing redundant network calls while keeping data fresh.

### 2. Data Normalization & Enrichment
- **Black‑76 IV Calculation**: Implied volatility for each strike is computed via the Black‑76 model, providing a consistent volatility surface.
- **Synthetic Futures Price**: Using put‑call parity on the ATM option, a synthetic futures price is derived for each expiry, enabling model‑consistent pricing when actual futures quotes are unavailable.
- **Strike‑Range & Multi‑Expiry Selectors**: UI components allow dynamic adjustment of the number of displayed strikes and selection of up to four expiries (indices) or two expiries (stocks). These parameters can be exposed as configurable inputs for downstream analytics.

### 3. Persistence & State Management
- **LocalStorage Persistence**: Selected underlying symbol and UI preferences are saved to localStorage, facilitating quick restoration of user context across sessions.
- **Redux Store**: Global state (data, UI flags, expiry selections) is managed via Redux, offering a predictable state container that can be integrated with eqats’ state‑management layer.

### 4. Visualization Toolkit (Optional Reuse)
- **D3‑Based Charts**: OI bar plots and strategy payoff line plots are rendered with D3, featuring tooltips and responsive scaling. While eqats may use its own charting library, the D3 implementation serves as a reference for rendering financial time‑series and payoff diagrams.

## Signal & Execution Logic – No Direct Mapping
The repository focuses on visualization and does not generate trading signals or execute orders. Consequently, there are no directly transferable components for eqats’ signal generation or order‑routing modules. However, the **strategy payoff calculation** (supporting up to 10 legs) could be adapted as a *signal‑evaluation* helper: given a portfolio of option positions, the same payoff engine can assess profitability at a target date or expiry, which may feed into signal‑validation logic.

## Risk Engineering – No Direct Mapping
No risk‑limit checks, position‑sizing algorithms, or real‑time risk monitors are present in the source. Therefore, no features map to eqats’ risk‑engineering domain. If risk‑metrics (e.g., Greeks, VaR) are required, they would need to be developed separately, possibly leveraging the existing IV and pricing engine as a foundation.

## Suggested Integration Steps for eqats

1. **Extract the Data‑Ingestion Layer**
   - Isolate the NSE API call functions and web‑worker scheduler into a reusable TypeScript package (e.g., `@eqats/nse-data-provider`).
   - Configure RTK Query (or eqats’ preferred caching solution) with the same 3‑minute TTL and refresh cadence.

2. **Adopt the Pricing & IV Engine**
   - Port the Black‑76 IV computation and synthetic futures price derivation into eqats’ analytics service.
   - Ensure unit tests cover edge cases (near‑zero time‑to‑expiry, extreme strikes).

3. **Reuse Configuration UI Components**
   - The strike‑range and expiry selectors (built with Material UI) can be wrapped as eqats‑compatible React components for strategy‑design wizards.

4. **Leverage LocalStorage Persistence Pattern**
   - Follow the same pattern for storing user‑selected underlyings, default expiry selections, or UI theme preferences within eqats’ frontend.

5. **Consider Payoff Engine for Signal Validation**
   - Expose the multi‑leg payoff function as a service that eqats’ signal‑validation module can call to verify that a generated signal meets a desired profit‑loss profile at expiry or a target date.

## Limitations & Notes
- The project’s IV calculations rely on synthetic futures prices; eqats should verify whether actual futures quotes are available for the instruments it trades and adjust the pricing model accordingly.
- No error‑boundary or retry logic is shown in the source; integrating robust error handling (e.g., exponential back‑off for NSE API failures) will be necessary for production use.
- The visualizer is a work‑in‑progress; future enhancements (e.g., FII/DII data, strategy presets) could be revisited for additional data‑engine features.

By incorporating the data‑ingestion, caching, and analytics components from `nse-oi-visualizer`, eqats can accelerate its coverage of Indian equity‑derivatives markets while maintaining a clean separation between data handling and signal/execution/risk layers.
