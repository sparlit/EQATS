# Integration Blueprint: nse-historical-data into eqats

## Overview
The 'nse-historical-data' npm package provides programmatic access to historical index data (P/E, P/B, Div Yield) for all indices listed on the National Stock Exchange (NSE) of India. It accepts a start and end date (ISO 8601) and returns a JSON structure where each date maps to an array of index objects containing price, volume, turnover and valuation ratios.

## Domain Mapping
- **Data Engines** – The package fits squarely in the Data Engines layer: it ingests raw market data from NSE's public endpoint and delivers it in a consistent, queryable format.
- **Signal & Execution Logic** – No native signal generation or order-routing capabilities.
- **Risk Engineering** – No risk-limit, sizing, or monitoring functions.

## Proposed Integration Steps

### 1. Data Ingestion Wrapper
Create a thin adapter in eqats's data-engine module:
```js
// eqats/data/engines/nseHistorical.js
const nseHistorical = require('nse-historical-data');

async function fetchNSEIndexData({ start, end }) {
  const options = { date: { start, end } };
  try {
    const raw = await nseHistorical(options);
    const normalized = Object.entries(raw).flatMap(([date, records]) =>
      records.map(rec => ({
        source: 'NSE',
        index: rec['Index Name'],
        date: new Date(rec['Index Date'].split('-').reverse().join('-')),
        open: parseFloat(rec['Open Index Value']),
        high: parseFloat(rec['High Index Value']),
        low: parseFloat(rec['Low Index Value']),
        close: parseFloat(rec['Closing Index Value']),
        volume: parseInt(rec['Volume'], 10),
        turnoverCr: parseFloat(rec['Turnover (Rs. Cr.)']),
        pe: parseFloat(rec['P/E']),
        pb: parseFloat(rec['P/B']),
        divYield: parseFloat(rec['Div Yield']),
      })));
    return normalized;
  } catch (err) {
    throw new Error(`NSE historical data fetch failed: ${err.message}`);
  }
}
module.exports = { fetchNSEIndexData };
```

### 2. Scheduling & Storage
- Use eqats's existing scheduler (cron-based or event-driven) to invoke the wrapper daily for the previous trading day or for a back-fill range.
- Persist the normalized records into eqats's time-series store (e.g., PostgreSQL with TimescaleDB) under a namespace like 'market_data.nse_indices'.

### 3. Feature Generation
Once stored, the data can be consumed by eqats's feature-engineering pipelines:
- Valuation ratios (P/E, P/B, Div Yield) as fundamental features for index-based strategies.
- Combine with price-based technical indicators (e.g., moving averages, RSI) to generate composite signals.
- Use turnover and volume as liquidity filters.

### 4. Consumption in Signal & Execution Logic
- Strategies that trade NSE index futures, ETFs, or constituent stocks can import the feature set via eqats's feature service.
- Example pseudo-code:
```js
const features = await eqats.featureService.get({
  source: 'NSE',
  index: 'Nifty 50',
  start: '2024-01-01',
  end: '2024-01-31',
  fields: ['pe', 'pb', 'divYield', 'close', 'volume']
});
// Build signal: go long if PE < 20 and DivYield > 1.5%
```

### 5. Risk Engineering Considerations
Although the package does not provide risk metrics, downstream risk modules can:
- Monitor index-level valuation extremes (e.g., PE > 30) as part of market-risk limits.
- Use turnover-derived liquidity scores to adjust position sizing.
- Incorporate dividend yield into cash-flow forecasting for portfolio-level risk.

## Benefits
- **India-specific coverage**: fills a gap for NSE index data that may not be present in eqats's default data vendors.
- **Fundamental ratios**: provides valuation metrics directly, reducing need for external fundamentals feeds.
- **Simple API**: promise-based/async-await interface fits well with eqats's Node.js-centric services.

## Limitations & Mitigations
- **Market-holiday gaps**: the service omits closed-market dates; eqats's storage layer should treat missing dates as non-trading periods.
- **Rate limiting**: relies on NSE's public site; implement caching and respectful request throttling in the wrapper.
- **Data validation**: add schema validation (e.g., Joi) after normalization to catch malformed fields.

## Conclusion
By wrapping 'nse-historical-data' as a data-engine adapter, eqats can enrich its Indian market coverage with reliable historical index fundamentals, enabling more sophisticated valuation-aware strategies while keeping signal and risk layers unchanged (they will consume the produced features).
