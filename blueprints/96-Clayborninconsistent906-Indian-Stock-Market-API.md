# Integration Blueprint for Indian-Stock-Market-API with eqats

## Overview
The Indian-Stock-Market-API provides a free, no-auth REST endpoint for real-time NSE and BSE stock prices and company data. This blueprint shows how to plug that data feed into the eqats quantitative trading platform, specifically into its Data Engines layer, while noting that the repository does not contribute directly to Signal & Execution Logic or Risk Engineering.

## 1. Prerequisites
- Python 3.6+ (as required by the API)
- Access to an eqats instance with Data Engine extensibility (e.g., ability to add custom market data adapters).
- Network access to the host running the Indian-Stock-Market-API (localhost or remote).

## 2. Deploy the Indian-Stock-Market-API
1. Download the latest release from the repository’s Releases page (or directly via the provided ZIP link).
2. Extract the archive and follow the OS-specific installation prompts.
3. Start the API:
   ```
   # Assuming the extracted folder contains a start script or entry point
   python -m indian_stock_market_api  # or however the project is launched
   ```
   The API will listen on http://localhost:5000 by default.
4. Verify endpoints:
   - Nifty 50: GET http://localhost:5000/nse/nifty50
   - BSE stocks: GET http://localhost:5000/bse/stock_prices
   Responses are JSON arrays/objects with price, symbol, timestamp, etc.

## 3. Create an eqats Market Data Adapter
Eqats expects market data adapters to implement a standard interface (e.g., subscribe(symbol, callback) and unsubscribe).

### Adapter Pseudocode (Python)
```python
import requests
import threading
import time

class IndianStockMarketAdapter:
    def __init__(self, base_url='http://localhost:5000', poll_interval=1):
        self.base_url = base_url
        self.poll_interval = poll_interval
        self._subscribers = {}  # symbol -> callback
        self._stop = threading.Event()

    def subscribe(self, symbol, callback):
        self._subscribers[symbol] = callback

    def unsubscribe(self, symbol):
        self._subscribers.pop(symbol, None)

    def _fetch_nse_nifty50(self):
        resp = requests.get(f'{self.base_url}/nse/nifty50', timeout=5)
        resp.raise_for_status()
        data = resp.json()  # expect list of {symbol, price, ...}
        for item in data:
            sym = item.get('symbol')
            if sym in self._subscribers:
                self._subscribers[sym](item)

    def _fetch_bse_stocks(self):
        resp = requests.get(f'{self.base_url}/bse/stock_prices', timeout=5)
        resp.raise_for_status()
        data = resp.json()
        for item in data:
            sym = item.get('symbol')
            if sym in self._subscribers:
                self._subscribers[sym](item)

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self._fetch_nse_nifty50()
                self._fetch_bse_stocks()
            except Exception as e:
                # log error; eqats can handle missing ticks
                pass
            time.sleep(self.poll_interval)

    def start(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def stop(self):
        self._stop.set()

# Usage within eqats Data Engine:
# adapter = IndianStockMarketAdapter()
# adapter.subscribe('RELIANCE', eqats.on_market_tick)
# adapter.start()
```

### Integration Steps
1. Place the adapter code in eqats’ data_engines/adapters/ directory (or equivalent plugin folder).
2. Register the adapter with eqats’ Data Engine configuration, e.g., add to market_data_providers: list.
3. Configure the poll interval (default 1 s) to match latency requirements.
4. Ensure the API host is reachable from the eqats runtime (Docker networking, host-mode, etc.).
5. Restart eqats Data Engine; it will now receive live NSE/BSE ticks via the adapter.

## 4. Data Normalization
The adapter maps the raw JSON fields to eqats’ canonical tick format:
- symbol → instrument.symbol
- price → tick.price
- timestamp (if provided) → tick.ts; otherwise use local receipt time.
- Additional fields (e.g., volume, change) can be stored in tick.metadata.

## 5. Signal & Execution Logic
The Indian-Stock-Market-API does not generate trading signals or handle order execution. Therefore, no direct integration points exist in the Signal & Execution Logic domain. Strategies should be built in eqats using the incoming market data from this adapter.

## 6. Risk Engineering
Similarly, the repository provides no risk-limit, position-sizing, or monitoring features. Risk controls must be implemented within eqats’ Risk Engineering modules (e.g., max-loss limits, volatility-based sizing) using the data supplied by this adapter.

## 7. Operational Considerations
- Reliability: The API is free and unauthenticated; monitor for downtime or rate-limits (though none are documented). Consider a fallback data source.
- Latency: Polling interval determines freshness; for sub-second needs, consider pushing data via websockets if the API ever supports it.
- Scalability: Multiple eqats instances can share the same API instance; each adds negligible load.
- Security: Since no auth is required, ensure the API is only exposed to trusted networks; otherwise place it behind a firewall or VPN.

## 8. Summary
- Data Engines: Real-time NSE/BSE price and company data via a simple REST endpoint; integrated via a lightweight polling adapter.
- Signal & Execution Logic: No features provided.
- Risk Engineering: No features provided.

By following the steps above, eqats can consume live Indian-stock market data from the Indian-Stock-Market-API and feed it into strategy and risk modules, completing a functional data pipeline for Indian-equity trading.