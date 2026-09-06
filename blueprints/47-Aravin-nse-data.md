# Integration Blueprint for eqats using nse-data

## Repository Summary
- **Name**: Aravin/nse-data
- **Primary Language**: TypeScript (Node.js)
- **Purpose**: Provides REST‑style APIs to fetch live and historical data from the National Stock Exchange (NSE) of India.
- **Key Features**:
  - Market status (`marketStatus`)
  - Symbol search (`searchSymbol`)
  - Equity historical data (`equityHistory`)
  - Equity meta‑info (`equityInfo`)
  - Equity options chain (`equityOptionChain`)
  - Equity real‑time quote (`equityQuote`)
  - Index details, info, list, and options chain (`indexDetails`, `indexInfo`, `indexList`, `indexOptionChain`)

## How the Features Map to eqats Domains

### Data Engines
All endpoints are pure market‑data ingestion tools. They can be wrapped as data‑engine adapters inside eqats to populate the market‑data store (e.g., a time‑series database or in‑memory cache) for:
- **Reference data**: symbol search and equity/info endpoints.
- **Price feeds**: equityQuote, equityHistory (historical candles), indexDetails.
- **Derivatives data**: equityOptionChain and indexOptionChain for volatility surfaces.
- **Market state**: marketStatus for trading‑session awareness.

### Signal & Execution Logic
The nse-data library does not generate trading signals or execute orders. However, the ingested data can be fed into eqats’ signal‑generation modules (e.g., moving‑average crossovers, volatility‑based signals) and execution adapters. A typical integration would:
1. Call the relevant endpoints on a scheduled basis (e.g., every minute for quotes, daily for historical).
2. Store the results in eqats’ market‑data layer.
3. Let eqats’ strategy engine read the stored data to produce signals.
4. Route signals to eqats’ execution layer (broker adapters) for order submission.

### Risk Engineering
No direct risk‑limit or position‑sizing features are present. Risk‑engineering components in eqats (e.g., VaR calculators, exposure limits, margin checks) can consume the same market data (prices, option chains) to compute risk metrics. The option‑chain endpoints are especially useful for Greeks‑based risk models.

## Integration Steps

1. **Add Dependency**
   ```bash
   npm install nse-data   # or yarn add nse-data
   ```

2. **Create a Data‑Engine Wrapper**
   ```ts
   // src/adapters/nseDataAdapter.ts
   import { nseData } from 'nse-data';

   export class NseDataAdapter {
     async getMarketStatus() {
       return nseData.marketStatus();
     }
     async searchSymbol(query: string) {
       return nseData.searchSymbol(query);
     }
     async getEquityHistory(symbol: string) {
       // series=['EQ'] is hard‑coded in the API; adjust if needed
       return nseData.equityHistory({ symbol, series: \\\"['EQ']\\\" });
     }
     async getEquityInfo(symbol: string) {
       return nseData.equityInfo({ symbol });
     }
     async getEquityOptionChain(symbol: string) {
       return nseData.equityOptionChain({ symbol });
     }
     async getEquityQuote(symbol: string) {
       return nseData.equityQuote({ symbol });
     }
     // Index wrappers omitted for brevity – follow same pattern
   }
   ```

3. **Schedule Data Pulls**
   Use eqats’ job scheduler (e.g., node‑cron or built‑in scheduler) to call the adapter methods at desired frequencies:
   - Quotes & market status: every 30 seconds during market hours.
   - Historical candles: once per day after market close.
   - Option chains: every 5 minutes for live Greeks calculation.

4. **Persist to eqats’ Market‑Data Store**
   Map each response to eqats’ canonical schema (e.g., \`priceBar\`, \`quote\`, \`optionChain\`) and write via the eqats data‑access layer (e.g., Sequelize, MongoDB, or a custom TimescaleDB wrapper).

5. **Consume in Strategies**
   Strategies import the eqats market‑data service, which now serves NSE‑sourced candles and quotes, enabling indicator calculations and signal generation.

6. **Risk‑Engineering Usage**
   Pull option‑chain data via the adapter, compute implied volatility surfaces and Greeks, feed into eqats’ risk‑module for margin‑requirement and position‑limit checks.

## Benefits
- **Zero‑cost data source**: Direct access to NSE’s public endpoints.
- **Typed responses**: TypeScript definitions reduce integration bugs.
- **Comprehensive coverage**: Equities, indices, and derivatives in a single package.

## Considerations
- Rate limits: NSE may throttle excessive calls; implement back‑off and caching.
- Data latency: Endpoints reflect delayed or real‑time data depending on the NSE feed; verify suitability for high‑frequency strategies.
- Authentication: No API key required for the public endpoints, but terms of use should be reviewed.

## Example Usage in eqats
   ```ts
   // src/services/marketDataService.ts
   import { NseDataAdapter } from '../adapters/nseDataAdapter'
   import { MarketDataRepository } from '../repositories/marketDataRepository'

   const adapter = new NseDataAdapter()
   const repo = new MarketDataRepository()

   export async function refreshEquityQuote(symbol: string) {
     const quote = await adapter.getEquityQuote(symbol)
     await repo.saveQuote({ symbol, ...quote, timestamp: new Date() })
   }

   // Schedule
   import cron from 'node-cron'
   cron.schedule('*/30 * 9-15 * * 1-5', () => refreshEquityQuote('RELIANCE'))
   ```

## Conclusion
By wrapping \`nse-data\` as a thin adapter layer, eqats gains reliable Indian‑market data feeds for its data‑engine, while signal generation, execution, and risk‑management components remain unchanged, consuming the standardized market‑data layer that eqats already provides.
