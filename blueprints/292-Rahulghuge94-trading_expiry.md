# Integration Blueprint for trading_expiry into eqats

## Overview
The `trading_expiry` library is a lightweight Python package that fetches NSE trading holiday data and computes weekly, next‑weekly, and monthly expiry dates for futures and options. Integrating it into eqats would give the project a reliable, up‑to‑date source of market‑calendar information without requiring custom scraping logic.

## Data Engine Integration
- **Holiday Ingestion**: Replace any manual holiday files with a call to `trading_expiry.fetch_holiday(year)` (internally uses `requests.get` to the NSE holiday‑master API).
- **Caching**: The library already writes `holiday_<year>.json` to the working directory; eqats can point its data‑engine to this directory or configure the library to write to a shared data lake (e.g., S3) by overriding the file path.
- **Expiry Computation**: Expose `week_expiry`, `next_week_expiry`, and `month_expiry` as derived attributes that eqats can query via a simple API wrapper (e.g., `get_nse_expiry()`).

## Signal & Execution Logic Integration
- Use the expiry dates to align strategy signals: only generate entry signals for options/futures contracts that expire on the computed dates.
- Filter out signals that would land on a holiday by checking the cached holiday set before order submission.
- The library itself does not execute trades; eqats’ execution engine would consume the calendar data and submit orders via its existing adapters.

## Risk Engineering Integration
- **Holiday Risk Guard**: Before allowing any position to be opened, eqats’ risk module can query the holiday set from `trading_expiry` to reject trades scheduled on NSE holidays.
- **Expiry‑Adjacent Risk**: Increase margin checks or reduce position size in the days leading up to expiry using the library’s expiry dates.
- **Monitoring**: Log holiday/expiry events for audit; the library’s JSON cache provides a persistent record.

## Implementation Steps
1. Add `trading_expiry` to eqats’ `requirements.txt` (or install via pip from the GitHub repo).
2. Create a thin wrapper module `eqats/data/nse_calendar.py` that:
   - Calls `trading_expiry.update_holiday(year)` on startup or daily.
   - Provides functions `is_trading_day(date)`, `get_weekly_expiry(date)`, `get_next_weekly_expiry(date)`, `get_monthly_expiry(date)`.
3. Update the signal generation pipeline to call `is_trading_day` before emitting a signal.
4. Hook the risk‑pre‑trade checks to consult the same calendar.
5. Optionally configure the library to write holiday JSONs to a shared storage bucket for multi‑instance consistency.

## Example Usage
```python
import trading_expiry
from eqats.data.nse_calendar import is_trading_day, get_monthly_expiry

# Ensure holiday cache is current for 2025
trading_expiry.update_holiday(2025)

if is_trading_day(today):
    signal = generate_signal()
    if signal:
        expiry = get_monthly_expiry(today)
        execute_order(signal, expiry)
```

## Benefits
- Eliminates bespoke holiday scraping, reducing maintenance burden.
- Guarantees consistency with NSE’s official calendar.
- Provides ready‑to‑use expiry calculations that can be leveraged across strategies, execution, and risk modules.

## Caveats
- The library relies on internet access to fetch the NSE API; in air‑gapped environments eqats must pre‑populate the holiday JSON files.
- No built‑in timezone handling; eqats should ensure dates are in IST before querying.
```