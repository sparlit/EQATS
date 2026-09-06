# Integration Blueprint for nsebsemcx into eqats

## Overview
The nsebsemcx repository provides a Python-based data engine that periodically fetches option chains, future chains, and tick data for NIFTY, BANKNIFTY, and FINIFTY from the National Stock Exchange (NSE) and stores the data as timestamped JSON files organized by date.

## Features
- **Periodic Fetching**: Every 30 seconds during market hours (09:15–15:45, Mon‑Fri) it retrieves live option and future chains.
- **After‑Hours Tick Data**: Post 15:45 it captures LTP/tick data for all currently trading expiries.
- **Organized Storage**: Data are saved under fetch_date/ folders with filenames containing timestamps, enabling easy historical retrieval.
- **Simple Scheduling**: Uses time‑based loops to respect the exchange schedule.

## eqats Domain Mapping
| eqats Domain          | Mapped Features                                                                 |
|-----------------------|---------------------------------------------------------------------------------|
| Data Engines          | Market data acquisition, scheduling, JSON serialization, file‑system storage.   |
| Signal & Execution Logic | None – the repository does not generate trading signals or execute orders.    |
| Risk Engineering      | None – no risk metrics, position sizing, or limit checks are performed.        |

## Integration Approach
Because the original implementation relies on Python‑specific NSE APIs and requires exchange credentials, a direct Rust rewrite would need to re‑implement those API calls and handle authentication. To keep the integration minimal and avoid fabricating unsupported capabilities, we provide a thin PyO3 wrapper that exposes the existing Python fetching logic as a Rust‑callable function. The wrapper can be invoked from the eqats Rust core to obtain fresh JSON data on demand.

## Files
- src/integrations/nsebsemcx.rs – Rust module with PyO3 bindings and a simple test.
