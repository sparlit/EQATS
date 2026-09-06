# Integration Blueprint for TickerStore into eqats

## Overview
TickerStore is a lightweight Python library that provides historical end-of-day data for Indian securities from the NSE and Upstox exchanges. It offers automatic fallback between sources, configurable fetch order, and easy credential handling via a .env file. This makes it an ideal candidate to serve as the 'Data Engine' component of the eqats quantitative trading platform.

## Proposed Integration

### 1. Dependency Management
Add tickerstore to the project’s requirements.txt or pyproject.toml:
```
tickerstore>=latest
python-dotenv>=latest
```

### 2. Wrapper Service
Create a thin wrapper in eqats/data_engines/tickerstore_adapter.py that exposes a uniform interface expected by eqats (e.g., get_historical(symbol, start, end, interval)). Example:
```python
from tickerstore.store import TickerStore
from dotenv import find_dotenv
from datetime import date

class TickerStoreAdapter:
    def __init__(self, fetch_order=None, dotenv_path=None):
        self.store = TickerStore(dotenv_path=dotenv_path)
        if fetch_order:
            self.store.set_fetch_order(fetch_order)
    
    def get_historical(self, symbol, start, end, interval='1d'):
        # Map interval string to TickerStore constants
        interval_map = {
            '1d': TickerStore.INTERVAL_DAY_1,
            # add other intervals if needed
        }
        return self.store.historical_data(symbol, start, end, interval_map.get(interval, TickerStore.INTERVAL_DAY_1))
```

### 3. Configuration
- Store Upstox credentials in a .env file at the project root (already supported).
- Optionally override fetch order via environment variables or eqats config (e.g., TICKERSTORE_FETCH_ORDER=NSE,UPSTOX).
- The adapter can read these variables and call set_fetch_order accordingly.

### 4. Usage in eqats Workflows
- **Backtesting**: Feed historical price series into eqats's backtesting engine via the adapter.
- **Live Trading**: Use the same adapter for the most recent daily bars; if intraday data is needed, extend the adapter to request smaller intervals (if TickerStore supports them).
- **Data Caching**: Cache fetched DataFrames locally to reduce API calls; the adapter can implement a simple file-based cache.

### 5. Testing
- Mock TickerStore.historical_data in unit tests to return synthetic DataFrames.
- Integration test using a real .env with sandbox Upstox credentials to verify fetch order fallback.

## Benefits
- Unified Access: Single API for NSE and Upstox with automatic fallback.
- Secure Credential Handling: Leverages python-dotenv, keeping secrets out of code.
- Flexibility: Adjustable fetch order lets eqats prioritize the more reliable or cheaper source.
- Minimal Footprint: Lightweight dependency, easy to vendor if needed.

## Limitations & Future Work
- Currently only end-of-day data; for tick-or minute-level data, additional sources or extensions would be required.
- No built-in rate-limit handling; eqats may need to implement throttling or retry logic.

## Conclusion
Integrating TickerStore as a data engine equips eqats with reliable, configurable historical market data for Indian equities, enhancing both backtesting fidelity and live-trading decision-making.
