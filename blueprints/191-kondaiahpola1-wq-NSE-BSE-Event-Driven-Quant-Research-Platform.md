# Integration Blueprint for eqats

## 1. Overview
The NSE‑BSE Event‑Driven Quant Research Platform provides a complete Indian‑market data pipeline, signal generation, and paper‑trading framework that can be plugged into the eqats architecture.

## 2. Data Engines Integration
- **Ingestion**: Replace eqats’ generic data loader with the platform’s MCP‑driven ingestors (`BhavcopyIngester`, `BseBhavcopyIngester`). They pull NSE/BSE bhavcopy and delivery files, write immutable raw Parquet with `source` and `raw_hash` lineage, and store them in a parquet lake.
- **Normalization & Quality**: Hook the platform’s normalization step and quality engine into eqats’ validation layer, ensuring every record carries canonical contracts (`InstrumentIdentity`, `MarketBar`, `CorporateAction`, `Announcement`, `OptionInstrument`, `OptionQuote`).
- **Storage**: Use the platform’s parquet lake for historical bars/delivery, and mirror the PostgreSQL schema for `cached_signals` and metadata. Redis can be reused as a hot‑cache layer with the same TTL (1 h) and refresh schedule (APScheduler).
- **Utilities**: Reuse the provided `make ingest`, `make validate`, `make sync` commands or invoke the underlying Python scripts (`scripts/bulk_ingest.py`, `scripts/cache_signals.py`) from eqats’ orchestration layer.

## 3. Signal & Execution Logic Integration
- **Signal Generation**: Adopt the delivery‑z‑score algorithm (`dz_hi_up` / `dz_hi_dn`) and market‑cap classification (including the SME override) as eqats’ alpha factors. The `cache_signals.py` script can be called to populate eqats’ signal table with additional technical indicators (RSI, MACD, SMA, ATR).
- **Backtesting**: Plug the platform’s NautilusTrader `ParquetDataCatalog` and `BacktestEngine` directly into eqats’ simulation module, allowing strategies to be tested on the same validated Indian‑market data.
- **Paper Trading & Live Execution**: Use the `paper_track.py` workflow (snapshot → settle → report) as a template for eqats’ paper‑trading engine. The GO‑LIVE gate (≥ 20 settled trades, ≥ +25 bps avg net return) can be enforced as a pre‑live risk check. The Upstox V3 adapters (REST historical, WebSocket feed, sandbox execution) provide a ready‑made broker‑interface layer for eqats to route orders to the Indian market.
- **Execution Flow**: In eqats, after signal generation, invoke the paper‑trading module to open positions, then the settlement module to close on stop‑hit or horizon, finally reporting performance via the same `report` command.

## 4. Risk Engineering Integration
- **GO‑LIVE Gate**: Implement the platform’s gate as a risk‑engineering pre‑live check in eqats: require a minimum number of settled paper trades and a threshold average net return before allowing live capital allocation.
- **Position‑Level Controls**: Reuse the stop‑hit and horizon logic from `paper_track.py settle` to enforce max‑loss or time‑based exits.
- **Limitations**: The repository does not expose explicit portfolio‑level risk limits, VaR, or leverage controls; eqats would need to add those layers on top of the provided trade‑level mechanics.

## 5. Implementation Steps
1. Fork the platform’s `src/indian_quant/schemas` and `scripts` directories into eqats’ `vendor/` or as a submodule.
2. Add a Docker Compose service for `nse-bse-mcp` (port 3000) and configure eqats’ ingestion pipeline to point at it.
3. Run `make ingest`, `make validate`, `make sync` to materialize the parquet lake and populate PostgreSQL/Redis.
4. Execute `python scripts/cache_signals.py` to warm the signal cache; schedule it with APScheduler (15 min interval).
5. Import the delivery‑z‑score and market‑cap functions into eqats’ signal library.
6. Wire NautilusTrader’s `ParquetDataCatalog` to eqats’ backtesting engine.
7. Adopt `paper_track.py` as the paper‑trading service, exposing `snapshot`, `settle`, and `report` endpoints.
8. Configure the Upstox V3 adapters (see `docs/adapter.md`) for live data feed and sandbox order routing.
9. Enforce the GO‑LIVE gate before switching from paper to live mode.
10. Monitor logs and Redis cache hits; adjust TTL or refresh frequency as needed.

By integrating these components, eqats gains a robust Indian‑market data engine, a proven delivery‑z‑score alpha signal, a ready‑to‑use backtesting/paper‑trading loop, and a basic risk‑gate that can be extended with eqats’ own risk‑engineering toolkit.