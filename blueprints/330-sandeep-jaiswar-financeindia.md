# Integration Blueprint: financeindia into eqats

## Overview
financeindia is a high‑performance Rust‑powered Python wrapper for NSE market data. It provides low‑latency access to equity, index, derivatives, SLB, commodities and macro‑data endpoints.

## Value for eqats
- Fast, reliable ingestion of Indian market data without managing cookies or rate‑limits manually.
- Typed PyO3 models simplify downstream processing.
- Can replace or supplement existing data feeds for NSE‑centric strategies.

## Proposed Integration (Data Engine Layer)

1. **Wrapper Module** (`eqats/data/financeindia_client.py`)
   - Initialize a singleton `FinanceClient`.
   - Expose async‑friendly wrappers (using `asyncio.to_thread`) for each endpoint.
   - Normalize responses to eqats canonical data classes (e.g., `Bar`, `Quote`, `OrderBook`).
   - Optional caching layer (e.g., `diskcache` or `redis`) for bhavcopy and historical series.

2. **Data Subscription**
   - Real‑time quotes via `get_equity_quote` polled at a configurable interval (respecting NSE TOS).
   - Historical backfill using `price_volume_data`, `get_index_history`, `get_option_chain`.
   - Macro data (FII/DII, market turnover) fetched daily for regime filters.

3. **Storage**
   - Raw JSON/PyO3 objects persisted to eqats’ data lake (Parquet/CSV) for audit.
   - Processed features written to feature store.

## Signal & Execution Logic
financeindia does not generate signals or execute orders. eqats would:
- Compute technical/fundamental signals on the normalized data streams.
- Route signals to execution adapters (e.g., broker APIs) as usual.

## Risk Engineering
Risk calculations (position limits, VaR, margin) would consume the ingested data:
- Use `get_span_margins` and `get_oi_limits_cli` for margin checks.
- Monitor `get_asm_stocks` / `get_gsm_stocks` for surveillance alerts.
- Incorporate FII/DII activity as a market‑risk factor.

## Deployment & Operational Notes
- Respect NSE/MCX terms: keep request rates low, implement exponential back‑off, and log 429 responses.
- The library’s cookie warm‑up helps avoid Akamai blocks; eqats should call `_initialize_session` once at startup.
- Deploy with Rust toolchain ≥1.88 for any custom builds; otherwise use the pre‑built manylinux wheel.
- Unit‑test wrapper using the existing `tests/test_client.py` as reference.

## Example Usage (pseudo‑code)

```python
from eqats.data.financeindia_client import IndiaDataEngine

data = IndiaDataEngine()
await data.initialize()

# Live quote
quote = await data.get_equity_quote("RELIANCE")
signal = my_strategy.on_quote(quote)

# Historical batch for backtest
bars = await data.price_volume_data(
    "RELIANCE", "01-03-2026", "05-03-2026"
)
engine.run_backtest(bars)
```

## Conclusion
By wrapping financeindia as a dedicated data‑engine component, eqats gains rapid, reliable access to the full breadth of NSE market data while keeping signal generation, execution, and risk logic within its own domain.
