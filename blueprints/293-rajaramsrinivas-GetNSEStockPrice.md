# Integration Blueprint for GetNSEStockPrice into eqats

## Repository Overview
- **Name**: GetNSEStockPrice
- **Language**: Python
- **Purpose**: Simple library to fetch NSE stock prices from Google and Yahoo Finance APIs.
- **Key Features**:
  - Retrieves price, volume, and timestamp for given scrip codes.
  - Available as both a Python library and a command‑line tool.
  - Includes optional email alert configuration via `config.py`.

## Domain Mapping
| eqats Domain | Relevant Features | Integration Notes |
|--------------|-------------------|-------------------|
| **Data Engines** | Market data ingestion from Google/Yahoo Finance REST endpoints. | Can replace or supplement existing market data feeds for NSE equities. The `get_stock_price` function returns a dict `{scrip: {price, volume, timestamp}}` which maps directly to eqats' market‑data cache format. |
| **Signal & Execution Logic** | None | The repository does not contain any signal generation, strategy logic, or order execution components. |
| **Risk Engineering** | None | No risk‑limit, position‑sizing, or monitoring features are present. |

## Suggested Integration Steps
1. **Wrap the fetch function**
   Create a thin adapter in `eqats/data_engines/nse_price_fetch.py`:
   ```python
   from GetNSEStockPrice import get_stock

   def fetch_nse_prices(scrips):
       raw = get_stock.get_stock_price(scrips)
       # Normalise to eqats internal schema
       return {
           sym: {
               "price": float(data["price"]),
               "volume": int(data["volume"]),
               "timestamp": data["timestamp"]
           }
           for sym, data in raw.items()
       }
   ```
2. **Register as a data source**
   Add the adapter to eqats' market‑data manager configuration under `data_sources.nse` so that the scheduler can call `fetch_nse_prices` at the desired frequency (e.g., every minute during market hours).
3. **Fallback handling**
   Since the library relies on public Google/Yahoo endpoints, implement a fallback to a primary data provider (e.g., NSE official feed) when the fetch fails or returns stale data.
4. **CLI utility**
   Expose the existing command‑line tool as an eqats sub‑command (`eqats fetch-nse --scrips TCS,INFY`) for ad‑hoc checks or debugging.
5. **Configuration & Alerts**
   Re‑use the optional `config.py` mechanism to set up SMTP alerts for fetch failures, integrating with eqats' existing alerting framework.

## Benefits
- Quick access to NSE equity prices without needing a costly data subscription.
- Simple Python dependency that can be vendored or installed via `pip`.
- Provides both programmatic and CLI access, fitting well into eqats' modular design.

## Limitations & Considerations
- Data latency and reliability depend on third‑party Google/Yahoo APIs; suitable for back‑testing or low‑frequency strategies but may need supplementation for high‑frequency trading.
- The library is unmaintained (last commit 2016); consider forking and updating to handle API changes or switching to `requests` with proper error handling.
- No built‑in rate‑limiting; implement a throttle in the adapter to avoid being blocked.

## Conclusion
The GetNSEStockPrice repository offers a lightweight market‑data ingestion component for NSE stocks. By wrapping its `get_stock_price` function, eqats can augment its data‑engine layer with an alternative NSE price source, while no direct contributions exist for signal/execution or risk domains.