# Integration Blueprint for pynse into eqats

## Overview
The pynse library provides a simple interface to fetch realtime and historical data from the National Stock Exchange of India (NSE). It can serve as a dedicated data engine for eqats when trading Indian equities.

## Data Engine Integration
- Replace or augment existing market data feeds with pynse for NSE‑specific instruments.
- Wrap Nse().info(symbol) and any historical fetch functions in eqats’ DataEngine abstraction to provide uniform get_quote(symbol) and get_history(symbol, start, end) methods.
- Cache responses locally to reduce website load and improve latency.

## Example Usage
```python
from pynse import Nse
from eqats.engine import DataEngine

class NseDataEngine(DataEngine):
    def __init__(self):
        self._client = Nse()
    def get_quote(self, symbol):
        return self._client.info(symbol)
    def get_history(self, symbol, start, end):
        # Assuming pynse provides a method like get_history
        return self._client.get_history(symbol, start=start, end=end)

# Register with eqats
engine = NseDataEngine()
eqats.set_data_engine('NSE', engine)
```

## Benefits
- Direct access to NSE’s website eliminates need for costly subscriptions for basic data.
- Simple installation (pip install pynse) and minimal dependencies.
- Enables eqats to expand coverage to Indian markets without major refactor.

## Considerations
- Data reliability depends on NSE website availability and any anti‑scraping measures.
- Rate limiting should be respected; implement retry/backoff.
- No built‑in support for order execution or risk controls; those must be handled elsewhere in eqats.

## Conclusion
Integrating pynse as a data engine equips eqats with a lightweight, free source of NSE realtime and historical data, facilitating strategy development for Indian equities while keeping the core signal/execution and risk layers unchanged.
