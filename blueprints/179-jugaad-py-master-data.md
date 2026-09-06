# Integration Blueprint: jugaad-py/master-data into eqats

## Overview
The `jugaad-py/master-data` repository offers ready‑to‑use master data for Indian equity markets (NSE/BSE). Its core asset is a curated holiday list and reference data for securities (symbols, lot sizes, tick sizes, etc.) exposed through a simple Python API.

## Value for eqats
- **Data Engines**: Holiday calendars are essential for correct back‑testing, live trading session detection, and avoiding order submission on market holidays. The security master data can be used to validate instrument identifiers, compute position sizes based on lot size, and adjust price ticks.
- **Signal & Execution Logic**: No direct signal generation or order execution components are present; integration would rely on eqats’ existing strategy framework.
- **Risk Engineering**: No built‑in risk limits or monitoring; however, the master data can support risk calculations (e.g., ensuring orders respect lot‑size multiples).

## Integration Steps
1. **Add Dependency**
   ```bash
   pip install jugaad-py==<version>
   ```
   (or install directly from GitHub if needed).

2. **Holiday Calendar Loader**
   Create a utility in eqats’ data engine layer:
   ```python
   from jugaad_data.nse import holidays
   
   def get_nse_holidays(year: int) -> list:
       return holidays(year)
   ```
   Use the returned list to filter out non‑trading days in the market‑data pipeline and to gate execution logic.

3. **Security Master Enrichment**
   ```python
   from jugaad_data.nse import stock_symbols
   
   def get_security_info(symbol: str) -> dict:
       # Returns lot size, tick size, face value, etc.
       return stock_symbols(symbol)
   ```
   Incorporate this info when:
   - Validating order quantities (must be multiples of lot size).
   - Applying tick‑size rounding to limit prices.
   - Computing notional values for risk checks.

4. **Data Refresh Schedule**
   - Holiday lists change annually; schedule a monthly job to pull the latest data from the package (which itself fetches from marketsetup.in).
   - Store the refreshed calendars in eqats’ internal feature store (e.g., Parquet or Redis) for low‑latency access.

5. **Testing**
   - Unit tests that verify holiday detection for known dates (e.g., Diwali, Independence Day).
   - Integration tests that confirm order sizing respects lot size using the master data.

## Expected Impact
- Eliminates hard‑coded holiday lists, reducing maintenance burden.
- Improves correctness of back‑tests and live trading by aligning with official exchange calendars.
- Enables automated lot‑size and tick‑size compliance, reducing operational risk.

## Limitations
- The package focuses on Indian markets; for other asset classes or global exchanges additional data sources would be needed.
- No real‑time updates; relies on periodic refreshes.

## Conclusion
Integrating `jugaad-py/master-data` equips eqats with reliable, exchange‑approved master data for NSE/BSE, strengthening the data engine foundation and supporting accurate signal generation, execution, and risk management without adding complexity to the strategy layer.