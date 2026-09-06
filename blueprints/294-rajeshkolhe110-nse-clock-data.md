# Integration Blueprint for nse-clock-data into eqats

## Overview
The `nse-clock-data` repository supplies a lightweight Python package for retrieving National Stock Exchange (India) trading‑hour information, holiday calendars, and real‑time market status. Its core utility is to answer the question “Is the market open right now?” and to provide upcoming open/close timestamps.

## Domain Mapping

### Data Engines
- **Market‑hours ingestion**: Functions like `get_market_status()`, `get_next_open()`, `get_next_close()` pull data from NSE’s public endpoints or fallback to a bundled holiday CSV.
- **Storage/caching**: Optionally writes the fetched holiday list to a local `holidays.csv` and caches the status for a configurable interval (e.g., 30 s) to reduce API calls.
- **Data format**: Returns a pandas `DataFrame` with columns `['timestamp', 'status', 'next_open', 'next_close']`, making it easy to merge with other market‑data feeds.

### Signal & Execution Logic
- **Time‑based gating signal**: The package exports `is_market_open(now=None)` which returns a boolean. Strategies can import this function and only generate/order‑execute when it returns `True`.
- **Session‑segment signals**: Helper functions `is_pre_open()`, `is_post_close()` allow strategies to differentiate between pre‑open, regular, and post‑close periods, enabling execution‑timing filters (e.g., only trade after 9:15 AM IST).
- **Execution hook**: A thin wrapper `execute_if_open(order_func, *args, **kwargs)` checks the clock before invoking the user‑supplied order placement function, preventing accidental orders outside market hours.

### Risk Engineering
- **No native risk features**: The repository does not contain position‑sizing logic, VaR calculations, risk‑limit checks, or real‑time P&L monitoring. Risk‑engineering concerns must be handled elsewhere in the eqats stack (e.g., via the existing risk‑management module).

## Integration Steps

1. **Add as dependency**
   ```bash
   pip install git+https://github.com/rajeshkolhe110/nse-clock-data.git
   ```
   (or package it and publish to PyPI if desired).

2. **Initialize the clock engine**
   In eqats’ data‑engine layer, instantiate a singleton:
   ```python
   from nse_clock_data import NSEClock
   clock = NSEClock(cache_ttl_seconds=30)
   ```

3. **Expose market‑status as a feature**
   - Create a new eqats feature `market_status` that calls `clock.get_market_status()` and stores the result in the feature store (e.g., Redis or TimescaleDB) for consumption by strategies.
   - Schedule a lightweight updater (e.g., every 30 s) to refresh the cache.

4. **Signal layer integration**
   - In the signal generation pipeline, add a pre‑filter:
     ```python
     if not clock.is_market_open():
         return []  # no signals when market closed
     ```
   - For strategies that need session awareness, use `clock.is_pre_open()` or `clock.is_post_close()` to adjust signal strength or execution logic.

5. **Execution layer integration**
   - Wrap existing order‑submission calls:
     ```python
     def safe_place_order(order):
         clock.execute_if_open(_place_order, order)
     ```
   - This guarantees that eqats will never send an order when NSE is closed, reducing operational risk.

6. **Monitoring & logging**
   - Log the market‑status changes (open → close, close → open) to eqats’ monitoring system for audit trails.
   - Since the package does not provide risk metrics, rely on eqats’ existing risk‑engine to monitor exposure, leverage, and P&L.

## Benefits
- **Reduced latency**: Local caching eliminates repeated HTTP calls to NSE.
- **Accuracy**: Uses NSE’s official holiday list, ensuring correct handling of special trading sessions.
- **Safety**: Automatic gating prevents out‑of‑hours order submissions, a common source of operational errors.
- **Simplicity**: Minimal dependencies (pandas, requests) keep the integration lightweight.

## Limitations & Mitigations
- **Coverage**: Only NSE (India) is supported; for other exchanges eqats would need similar clock packages.
- **No risk controls**: Must rely on eqats’ risk‑engine for position limits, stop‑loss, etc.
- **Data freshness**: Cache TTL should be tuned; set low enough (e.g., 10 s) during volatile periods to catch unscheduled holidays.

## Conclusion
Integrating `nse-clock-data` equips eqats with a reliable, low‑overhead market‑clock service that cleanly separates time‑based gating from strategy logic and execution, thereby enhancing operational safety without adding complexity to the risk‑management layer.