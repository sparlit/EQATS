# Integration Blueprint: OpenChart Data Engine for eqats

## Overview
OpenChart provides programmatic access to NSE India equity, index, and derivatives historical data. This blueprint outlines how to incorporate OpenChart as a data engine within the eqats quantitative trading framework.

## Integration Points

### 1. Data Engine Layer
- Replace or augment existing market data adapters with an `OpenChartDataEngine` class.
- Implement `fetch_historical(symbol, segment, start, end, timeframe)` returning a pandas DataFrame with columns ['Open','High','Low','Close','Volume'] indexed by timestamp.
- Implement `search_symbols(query, segment)` to discover tradable instruments.

### 2. Configuration
- Add `openchart` to eqats `requirements.txt` or environment.
- No API keys required; configure optional cache directory to avoid repeated downloads.

### 3. Usage Example within eqats
```python
from eqats.data_engines import OpenChartDataEngine
from datetime import datetime, timedelta

engine = OpenChartDataEngine()
end = datetime.now()
start = end - timedelta(days=30)

# Get NIFTY 50 daily candles
df = engine.fetch_historical('NIFTY 50', 'IDX', start, end, '1d')
# df ready for feature generation, backtesting, or live signal computation
```

### 4. Benefits
- Broad coverage of Indian market (indices, equities, futures, options).
- Multiple timeframes from 1‑minute to monthly enable multi‑resolution strategies.
- Zero‑auth simplifies deployment in research environments.

### 5. Considerations
- Data is sourced from NSE's public charting endpoints; validate against official sources for production.
- Rate limits are not documented; implement retry/backoff if needed.
- No real‑time streaming; suitable for end‑of‑day or periodic batch ingestion.

## Conclusion
By integrating OpenChart as a dedicated data engine, eqats gains reliable access to NSE India historical data, expanding its market scope and enabling strategy development on Indian equities and derivatives without additional authentication overhead.
