# Integration Blueprint: nse-options-data-collector → eqats

## Overview
The `nse-options-data-collector` repository provides a robust, scheduled data‑engine for Indian NSE futures & options market data. It collects OI snapshots, full option chains (with Greeks), global market cues, and end‑of‑day candles, storing everything as partitioned Parquet files. This blueprint outlines how its most valuable components can be plugged into the eqats quantitative trading platform to enhance data availability, signal generation, and deployment reliability.

---

## 1. Data Engine Integration

### 1.1 Ingestion Pipeline
- **Scheduler**: Reuse the existing 15‑minute cron‑like schedule (9:20‑15:29 IST) for OI and option‑chain collectors, plus pre‑market (8:45, 10:00) and EOD (16:00) collectors. In eqats, wrap these as `eqats.data.collectors.nse_options` tasks that can be triggered via the platform’s orchestration layer (e.g., Airflow, Prefect, or eqats’ native scheduler).
- **Instrument Resolution**: Leverage the automatic Upstox Symbol Search and lot‑size fetch to dynamically map eqats symbol identifiers (e.g., `NIFTY`, `RELIANCE`) to Upstox instrument keys. Cache the mapping locally (`data/oi_snapshots/_instrument_keys.json`) to minimise API calls—eqats can persist this cache in its shared storage layer.
- **Data Validation**: Add lightweight schema checks (using `pandera` or eqats’ validation utilities) on incoming Parquet rows to ensure required fields (`timestamp`, `symbol`, `strike`, Greeks, etc.) are present before persisting.

### 1.2 Storage & Format
- **Parquet Partitioning**: Adopt the existing folder layout (`data/oi_snapshots/`, `data/option_chain/`, etc.) as eqats’ raw‑data lake. eqats can then create curated views (e.g., daily OI summary, rolled‑forward option‑chain surfaces) using its data‑transformation framework (dbt, Spark, or Polars).
- **Incremental Writes**: The collectors already append to date‑specific Parquet files (e.g., `oi_2025-08-05.parquet`). eqats should treat these as immutable partitions and compact/optimize them periodically (e.g., nightly VACUUM or Delta Lake merge) for query performance.

### 1.3 Deployment & Ops
- Follow the VPS guide to deploy the collectors on a low‑cost cloud VM (Oracle Cloud Free Tier, AWS t4g.micro, etc.). eqats’ DevOps charter can encapsulate the deployment steps into a Helm chart or Docker Compose service, ensuring the collectors run as side‑car containers alongside the eqats strategy engine.
- Monitoring: Export collector logs to eqats’ centralized logging (e.g., Loki) and expose a simple health‑check endpoint (e.g., last successful snapshot timestamp) for alerting.

---

## 2. Signal & Execution Logic Enhancement

### 2.1 Ready‑Made Signal Features
The collectors output columns that map directly to common quantitative signals:
- **OI‑Based Signals**: `ce_oi_signal`, `pe_oi_signal` (long build / short cover) – can be used as bias filters in equity‑ or index‑based strategies.
- **Put‑Call Ratio (PCR)**: `pcr` and `pcr_change` – useful for mean‑reversion or sentiment‑driven signals.
- **Max OI Strikes**: `max_ce_oi_strike`, `max_pe_oi_strike` – act as magnetic price levels; eqats can compute distance‑to‑max‑OI features.
- **ATM Greeks & IV**: `atm_ce_ltp`, `atm_pe_ltp`, `ce_iv`, `pe_iv`, plus per‑strike Greeks (`delta`, `theta`, `gamma`, `vega`) – essential for volatility‑sensitive strategies, delta‑hedging P&L attribution, and gamma‑scalping signals.
- **Bid/Ask Spread**: `ce_bid`, `ce_ask`, `pe_bid`, `pe_ask` – can be used to gauge liquidity and adjust slippage models.

These features can be ingested by eqats’ signal‑generation modules (e.g., `eqats.signals.nse_options`) and combined with alternative data (news, macro) to produce alpha.

### 2.2 Execution Considerations
The repository does **not** contain order‑execution or broker‑integration code. To turn signals into live trades:
1. **Signal Export**: Have the collectors write a `signals.parquet` (or update a Redis cache) that eqats’ execution engine subscribes to.
2. **Execution Adapter**: Build a thin adapter in eqats that reads the latest signal snapshot, checks risk limits, and routes orders via the desired broker (Upstox, Zerodha, etc.) using eqats’ existing execution abstraction layer.
3. **Latency**: Since data is collected at 15‑minute intervals, strategies based on this data will be low‑frequency (intraday swing or positional). For higher‑frequency needs, consider increasing collection frequency (requires API rate‑limit review).

---

## 3. Risk Engineering – Gap Note
The nse-options-data-collector does not provide explicit risk‑limit checks, position‑sizing logic, or real‑time risk monitoring. These responsibilities remain with eqats’ risk engine. However, the rich dataset it supplies (OI changes, IV term structure, Greeks) can enhance eqats’ risk models:
- **Volatility Risk**: Use per‑expiry IV and vega to estimate portfolio volatility exposure.
- **Liquidity Risk**: Monitor bid/ask spreads and OI concentration to adjust position‑size limits.
- **Concentration Risk**: Track max OI strikes to avoid overexposure to pinned levels.

Integrate these metrics as inputs to eqats’ risk‑calculators (VaR, stress testing, margin‑usage).

---

## 4. Summary of Value to eqats
| Feature | Benefit to eqats |
|---------|------------------|
| Automated 15‑min NSE OI & option‑chain collection | Reliable, low‑latency fundamentals for derivatives strategies |
| Global cues & EOD candles | Enables macro‑regime filters and end‑of‑day rebalancing |
| Parquet‑based partitioned storage | Fits naturally into eqats’ data lake architecture |
| Automatic instrument‑key & lot‑size resolution | Reduces maintenance overhead when expanding the universe |
| Rich signal columns (OI signals, PCR, Greeks, IV) | Direct feed for strategy research and live signal generation |
| VPS deployment guide | Simplifies ops for always‑on data collection in a cost‑effective manner |

By wrapping the collectors as eqats data‑ingestion services, consuming their output as signal features, and leveraging the data for enhanced risk analytics, eqats can rapidly expand its coverage of Indian index and stock options without building a low‑level data pipeline from scratch.

---

*Next Steps*: 
1. Fork the repository into eqats’ monorepo under `libs/nse_options_collector`.
2. Create an eqats‑specific wrapper that calls the existing collector scripts or refactors them into importable modules.
3. Add unit tests that validate the Parquet schema against eqats’ canonical contracts.
4. Deploy a test VPS instance, verify daily runs, and hook the output into eqats’ feature store.
5. Develop signal plugins that consume the OI‑signal and Greeks columns and emit eqats‑compatible signal events.
6. Update eqats risk‑model configs to ingest the new volatility and liquidity metrics derived from the collected data.
