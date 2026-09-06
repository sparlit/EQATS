# Breadth Radar Integration Blueprint

## Overview
The breadth-radar repository provides an HTML/JavaScript dashboard for visualizing NSE market breadth metrics. Its core value lies in the data acquisition pipeline and breadth‑signal calculations that can be reused within the eqats quantitative trading framework.

## Data Engine Integration
- **Market Breadth Ingestion**: The repo fetches advance/decline, new highs/lows, and volume data from NSE public endpoints (likely via `fetch` calls). This logic can be extracted into a reusable eqats data‑engine module that normalizes the raw JSON into a common market‑breadth schema.
- **Caching / Refresh**: Implements periodic polling (e.g., every 30 s) and optional localStorage caching. eqats can replace the client‑side cache with its own time‑series store (e.g., Redis or a database) while keeping the same refresh interval.
- **Error Handling**: Includes retry on failed requests and fallback to stale data—patterns that align with eqats’ resilient ingestion guidelines.

## Signal & Execution Logic Integration
- **Breadth Signals**: The dashboard computes indicators such as the Advance‑Decline Line, McClellan Oscillator, and Breadth Thrust ratio. These formulas can be ported to eqats’ signal library as pure functions that accept the normalized breadth series.
- **Signal Generation**: By exposing a `getSignals()` function that returns a signal object (e.g., `{bullish: true, strength: 0.7}`), eqats can subscribe to these signals via its event bus and feed them into strategy modules.
- **Execution Hooks**: Although the original repo is visualization‑only, the signal output can be wired to eqats’ execution adapter to generate market‑on‑close or intraday orders based on breadth thresholds.

## Risk Engineering Integration
- **Risk Monitoring**: The radar highlights overbought/oversold breadth conditions (e.g., McClellan > +100 or < -100). eqats can treat these as risk flags that trigger position‑size scaling or trading halts.
- **Dynamic Limits**: Implement a risk‑engine module that reads the breadth‑risk flag and adjusts max‑leverage or sector‑exposure limits in real time.
- **Health Checks**: The repo’s data‑freshness indicator (last‑update timestamp) can be used as a data‑quality gate in eqats’ risk‑pre‑trade checks.

## Implementation Steps
1. Extract the data‑fetching functions (`fetchNSEBreadth()`) into a TypeScript module within `eqats/engines/data/marketBreadth.ts`.
2. Create a schema adapter that maps the raw NSE payload to eqats’ `MarketBreadth` interface.
3. Implement the breadth‑indicator library (`eqats/signals/breadth.ts`) reproducing the McClellan Oscillator, Breadth Thrust, etc.
4. Expose a `BreadthSignalProvider` class that emits signals on eqats’ event loop.
5. Add a risk‑monitor plugin (`eqats/risk/breadthRisk.ts`) that subscribes to the signal and updates risk limits.
6. Write unit tests using the sample JSON payloads found in the repo’s `data/` directory (if any) or mock NSE responses.
7. Deploy the module and verify integration in a paper‑trading environment before live use.

## Considerations
- The original repo relies on browser‑only APIs (e.g., `localStorage`). For server‑side eqats deployment, replace client storage with a persistent cache.
- NSE data may be subject to usage limits; ensure compliance with NSE’s data‑policy when scaling the ingestion frequency.
- Since the repository lacks a detailed README, validate any extracted logic against the actual source code before integration.