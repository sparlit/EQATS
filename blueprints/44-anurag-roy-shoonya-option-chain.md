# Integration Blueprint for shoonya-option-chain into eqats

## Overview
The shoonya-option-chain repository provides a live option chain UI built with Next.js that consumes Finvasia Shoonya APIs, stores instrument data in SQLite, and allows direct sell order placement from the UI. These capabilities map well to the eqats domains.

## Data Engines
- **Market Data Ingestion**: Replace the Shoonya API calls with eqats' universal data adapter to pull real‑time option chain quotes (bid, ask, LTP) and push them through eqats' WebSocket or message bus.
- **Instrument Storage**: Use eqats' feature store (or PostgreSQL) to persist the instrument master data instead of SQLite; the existing `npm run data:prepare` script can be adapted to load eqats' instrument metadata.
- **Grouped Stock Monitoring**: eqats' watchlist service can reuse the `GROUPS` configuration to create user‑defined watchlists that update in real time.
- **Strike Filtering**: The `DIFF_PERCENT` logic can be exposed as a configurable filter in eqats' data pipeline to exclude deep‑OTM contracts, reducing bandwidth.

## Signal & Execution Logic
- **Order Entry UI**: The sell‑order button can be wrapped as an eqats order‑ticket component that calls eqats' execution gateway (REST or WebSocket) with the same parameters (symbol, quantity, price).
- **Multi‑Tab Support**: eqats' frontend already supports multiple workspaces; the option‑chain view can be added as a widget that can be instantiated in separate tabs.
- **Execution Hooks**: Leverage eqats' pre‑trade risk checks (e.g., max notional, price bands) before forwarding the order to the broker.

## Risk Engineering
- No native risk limits are present in the repo. However, the `DIFF_PERCENT` threshold can be treated as a risk parameter that limits the strike width displayed (and thus tradable). In eqats, this can be mapped to a max‑strike‑distance rule in the option‑strategy risk module.
- Additional risk checks (position limits, margin, VaR) should be added in eqats' risk layer when integrating the order ticket.

## Adaptation Steps
1. **Data Layer**
   - Create an eqats adapter for Shoonya API (or use existing broker adapter) that subscribes to option chain ticks.
   - Store instrument master in eqats' feature store; run a migration script similar to `data:prepare`.
2. **UI Integration**
   - Export the option‑chain table as a reusable React component.
   - Plug the component into eqats' dashboard layout; expose `GROUPS` and `DIFF_PERCENT` via eqats' settings service.
   - Replace the direct `placeSellOrder` call with a dispatch to eqats' order‑ticket API.
3. **Execution & Risk**
   - Wrap order submission with eqats' pre‑trade validation middleware.
   - Add risk‑limit configuration (max notional per strike, max total gamma) in eqats' risk service.
4. **Testing & Deployment**
   - Write unit tests for the adapter using mock Shoonya responses.
   - Deploy the component as part of eqats' Next.js app or as a micro‑frontend via module federation.

## Example Snippet (TypeScript)
```ts
// eqats adapter skeleton
import { ShoonyaClient } from '@eqats/broker-shoonya';
import { OptionChainSnapshot } from '@eqats/types';

export async function fetchOptionChain(symbol: string): Promise<OptionChainSnapshot> {
  const client = new ShoonyaClient({ apiKey: process.env.SHOONYA_KEY });
  const raw = await client.getOptionChain({ symbol });
  return {
    timestamp: Date.now(),
    underlying: raw.ltp,
    calls: raw.ce.map(c => ({ strike: c.strike, bid: c.bid, ask: c.ask })),
    puts: raw.pe.map(p => ({ strike: p.strike, bid: p.bid, ask: p.ask })),
  };
}
```

## Conclusion
By re‑using the live‑data ingestion, instrument storage, and order‑entry UI from shoonya-option-chain, eqats can rapidly add a fully‑featured option‑chain widget while retaining its centralized risk and execution framework.
