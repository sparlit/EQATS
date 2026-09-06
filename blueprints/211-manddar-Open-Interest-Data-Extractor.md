# Integration Blueprint: Open-Interest-Data-Extractor into eqats

## Overview
The Open-Interest-Data-Extractor repository provides a lightweight Python script that fetches the NIFTY and BANKNIFTY option chains from the NSE India website, extracts Open Interest (OI) data, and outputs it either as a colour‑coded console table or as raw JSON. Its core strengths lie in reliable market‑data ingestion, automatic cookie/session handling, retry logic on 401 errors, and clean separation between data fetching (`fetch_json`) and presentation (`print_oi_table`). These characteristics make it an ideal candidate for eqats’ **Data Engines** layer.

## Data Engine Features to Reuse
- **Live OI ingestion** – `fetch_json(session, symbol, strikes)` performs an HTTP request to NSE, parses the JSON payload, and returns structured option‑chain data.
- **Configurable strike window** – `-n/--strikes` lets the caller specify how many strikes above/below the ATM to retrieve (default 5 for NIFTY, 10 for BANKNIFTY).
- **Formatted output** – OI numbers are rendered with thousand separators; optional colour table via ANSI codes.
- **Raw JSON export** – `--json` (and `--pretty`) dump the exact NSE payload, enabling downstream processing.
- **Robust networking** – automatic cookie jar via `requests.Session()`, 401 retry with correct URL, comprehensive error handling (network, HTTP, JSON decode).
- **CLI‑driven but import‑safe** – `if __name__ == "__main__"` guard allows the module to be imported without side effects.

## Proposed Integration into eqats
1. **Wrap the fetcher as an eqats Data Engine plugin**
   Create a new module `eqats/data_engines/nse_oi.py` that exposes a class `NSEOIEngine` implementing eqats’ `DataEngine` interface:
   ```python
   class NSEOIEngine(DataEngine):
       def __init__(self, symbol="both", strikes=None):
           self.symbol = symbol
           self.strikes = strikes
           self.session = requests.Session()
        
       def fetch(self):
           raw = fetch_json(self.session, self.symbol, self.strikes)
           # Transform raw NSE payload into eqats canonical OI format
           return self._normalize(raw)
   ```
   The `_normalize` method would extract `ce_oi`, `pe_oi`, strike price, and expiry for each row, adding timestamps and source metadata.

2. **Reuse existing CLI flags as engine configuration**
   Map `-s/--symbol` → `symbol`, `-n/--strikes` → `strikes`, `--json` → a flag that returns the raw NSE JSON instead of the normalized form (useful for debugging or direct consumption by other eqats components).

3. **Integrate with eqats’ scheduling / streaming layer**
   Register `NSEOIEngine` with eqats’ data‑engine scheduler (e.g., a periodic task running every 30 seconds during market hours). The engine’s output can be published to an internal topic (Kafka/Pulsar) or written directly to the timeseries store.

4. **Leverage error‑handling and retry logic**
   The existing retry on 401 and exception handling can be kept unchanged; eqats can wrap the call in its own retry policy for additional resilience.

5. **Optional colour‑table output for debugging**
   Provide a helper function `print_oi_table(data, no_color=False)` that eqats’ CLI or admin scripts can call to display a quick OI snapshot in the terminal, mirroring the original tool’s usability.

## Benefits for eqats
- **Rapid access to high‑frequency OI data** for indices that are otherwise costly or restricted.
- **Standardised JSON pipeline** enabling downstream signal modules to compute PCR, OI‑change, max‑pain, etc., without re‑implementing the NSE scrape.
- **Reduced maintenance** – the extractor already handles session cookies, retries, and error reporting.
- **Extensibility** – the same pattern can be applied to other NSE derivatives (e.g., FinNifty) by adjusting the endpoint and symbol mapping.

## Deployment Considerations
- **VPN / IP restrictions** – as noted in the README, NSE blocks non‑Indian IPs. Deploy the engine on nodes with an Indian IP or use an Indian exit proxy.
- **Rate limiting** – NSE may throttle rapid calls; respect a reasonable interval (e.g., ≥5 s) and incorporate back‑off.
- **Dependency** – only `requests` is required; ensure it is listed in eqats’ `requirements.txt`.
- **Testing** – unit tests can mock `fetch_json` to return sample NSE payloads, verifying the normalization logic and error paths.

## Example Usage within eqats
```python
from eqats.data_engines.nse_oi import NSEOIEngine

engine = NSEOIEngine(symbol="nifty", strikes=5)
oi_data = engine.fetch()   # List of dicts with strike, ce_oi, pe_oi, timestamp, …
# Publish to internal bus
eqats.bus.publish("market.oi.nifty", oi_data)
```

## Summary
By extracting the data‑fetching core (`fetch_json`) and the optional display helpers from Open‑Interest-Data-Extractor and wrapping them in an eqats‑compliant Data Engine, we gain a reliable, low‑latency source of NIFTY/BANKNIFTY Open Interest. This enriches eqats’ market‑data foundation, enabling more sophisticated options‑focused signals and risk metrics while re‑using battle‑tested networking and error‑handling code.
