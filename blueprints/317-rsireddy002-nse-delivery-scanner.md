# Integration Blueprint: nse-delivery-scanner → eqats

## Overview
The nse-delivery-scanner repository provides a robust pipeline for fetching NSE cash-market delivery data, cleaning it, computing delivery‑based metrics, and persisting the results as a partitioned Parquet dataset. It also includes a lightweight Streamlit dashboard for interactive exploration.

## Data Engine Integration
- **Ingestion** – Reuse the `deliv_fetch.py` logic (session‑primed `requests.get`, leading‑space stripping, `"-"` → NaN, HTML‑length holiday check) to pull the daily `sec_bhavdata_full_*.csv` from NSE archives directly into eqats’ raw data lake.
- **Storage & Caching** – Adopt the Parquet write pattern (`data/delivery_latest.parquet` + `delivery_meta.json`) as a daily snapshot in eqats’ `data/delivery/` folder, enabling fast downstream reads and version‑control via Git (or DVC).
- **Feature Engineering** – Port the calculated columns:
  - `DELIV_QTY` (demat delivery quantity)
  - `DELIV_VAL_CR` (delivery value in ₹ cr)
  - `DELIV_PER` (delivery % of traded quantity)
  - `DELIV_RVOL` (today’s delivery vs. median of prior N sessions, with ≥3‑session guard)
  These become alternative‑data factors that can be joined to eqats’ standard OHLCV universe.
- **BE‑Series Filter** – Exclude BE series rows by default (or keep a flag) to avoid distorted `DELIV_PER` rankings.
- **Update Cadence** – Wrap the existing `precompute.py` script (run after 19:00 IST) into an eqats cron job or Airflow DAG that commits the new Parquet to the repo’s `data/` branch or pushes to an S3‑backed lake.

## Signal & Execution Logic Integration
*The scanner itself does not generate trade signals or execute orders.*
However, the delivery‑based factors it produces can be consumed by eqats’ signal layer:
- **Factor Construction** – Create z‑scores or percentile ranks of `DELIV_PER` and `DELIV_RVOL` across the NSE universe each day.
- **Signal Examples**
  - **Accumulation Signal**: High `DELIV_PER` (>80th percentile) together with positive `CHG_PCT`.
  - **Distribution Signal**: High `DELIV_PER` with negative `CHG_PCT` (as noted in the README).
  - **RVOL Breakout**: `DELIV_RVOL` > 2.0 indicating unusually strong institutional delivery relative to recent history.
- **Execution** – Feed these signals into existing eqats strategy templates (e.g., mean‑reversion, momentum) as additional filters or as primary alpha sources. No changes to order‑routing logic are required.

## Risk Engineering Integration
*The repository does not contain explicit risk limits or position‑sizing logic.*
Nevertheless, the delivery data can enhance eqats’ risk monitoring:
- **Concentration Risk** – Monitor stocks with extreme `DELIV_QTY` or `DELIV_VAL_CR` as potential liquidity sinks; flag if a single security exceeds a configurable % of total delivery volume.
- **Stress Testing** – Use historic `DELIV_RVOL` spikes as scenarios for liquidity‑stress models.
- **Exposure Controls** – Incorporate `DELIV_PER` thresholds into portfolio construction to avoid over‑exposure to stocks showing abnormal delivery behavior that may precede price pressure.

## Implementation Steps
1. **Copy Ingestion Code**
   - Add `eqats/data_engines/nse_delivery_fetch.py` (adapted from `deliv_fetch.py`).
   - Ensure session priming, space stripping, and NaN handling are preserved.
2. **Daily ETL Job**
   - Create an Airflow DAG (or eqats cron) that runs the fetch script after 19:00 IST, writes `data/delivery/delivery_YYYYMMDD.parquet` and updates a `latest` symlink.
   - Store metadata (run timestamp, row count, NSE holiday flag) in a companion JSON.
3. **Feature Store Integration**
   - Register the Parquet as a dataset in eqats’ feature store (e.g., Feast or internal catalog) with columns `symbol, date, DELIV_QTY, DELIV_VAL_CR, DELIV_PER, DELIV_RVOL`.
   - Provide a point‑in‑time join API for strategy back‑testing.
4. **Signal Module**
   - Implement `eqats/signals/delivery_factor.py` that reads the feature store, computes percentile ranks, and outputs the three signal flags described above.
   - Wire the module into the existing signal aggregation pipeline.
5. **Risk Dashboard Extension**
   - Add a new tab to the eqats risk monitoring Streamlit app (or Grafana) showing top‑10 stocks by `DELIV_QTY`, `DELIV_VAL_CR`, and `DELIV_RVOL`, with alerts when thresholds are breached.
6. **Testing & Validation**
   - Unit‑test the ingestion helpers against sample CSV files (including edge cases: leading spaces, `"-"`, holiday HTML).
   - Back‑test the delivery‑based signals on historical NSE data to verify information coefficient before live deployment.

## Expected Benefits
- **Alternative Data Edge** – Delivery‑based metrics capture institutional flow not reflected in price or volume alone.
- **Low Latency** – Daily Parquet snapshots enable sub‑second retrieval for intraday strategy checks.
- **Robustness** – The scanner already handles NSE’s quirky CSV format, holiday pages, and missing data, reducing data‑pipeline fragility.
- **Synergy** – Combines well with existing eqats factors (e.g., VWAP, momentum) to improve signal quality and risk awareness.