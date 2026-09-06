# Integration Blueprint for eqats: NSE Options Data Analysis Toolkit

## Overview
The `nse-options-last-5-years` repository provides a production‑ready pipeline for downloading, enriching, and storing five years of NSE derivatives data. It computes implied volatility (IV), realised volatility (RV), Greeks, IV‑percentile/rank, and persists the enriched records either as a JSON file or directly into a PostgreSQL database with JSONB columns.

## Data Engine Features to Integrate
- **Ingestion**
  - Automated download of NSE Bhavcopy ZIPs → CSV extraction (`download_bhavcopy.py`).
  - Retrieval of underlying spot prices from Yahoo Finance (`download_yahoo_data.py`).
  - FBIL MIFOR interest‑rate CSV handling.
  - Earnings‑calendar JSON ingestion.
- **Analytics Engine**
  - Black‑Scholes + bisection IV calculation for 30/60/90 d expiries.
  - Yang‑Zhang realised volatility.
  - Full Greeks (Δ, Γ, Θ, ν, ρ).
  - Rolling 30‑day IV percentile and rank.
  - Index‑aware weekly‑expiry bucketing.
- **Storage Options**
  - Write enriched JSON to `processed_data/processed_data.json`.
  - Recommended bulk‑upsert into PostgreSQL via `store_in_db/store_s.py` (multithreaded, connection pooling, automatic retries, configurable batch size).
- **Performance**
  - Multithreaded symbol processing; NumPy releases GIL for near‑linear CPU scaling.
  - Configurable `BATCH_SIZE`, `MAX_WORKERS`, `STATEMENT_TIMEOUT` via environment variables.
- **Visualization Hooks**
  - `interactive_view/` provides a Plotly/Dash sandbox that can read directly from PostgreSQL or the JSON file.

## Signal & Execution Logic
The repository does **not** contain any signal generation, strategy logic, or order‑execution components. It is purely an analytics/data‑engineering toolkit. Therefore, no direct features map to the Signal & Execution domain; eqats would need to supply its own signal/model layer that consumes the enriched option metrics produced by this pipeline.

## Risk Engineering
Similarly, there are no explicit risk‑limit, position‑sizing, or risk‑monitoring modules. The computed IV percentile/rank and Greeks can be used as inputs for risk models, but the repo itself does not enforce risk controls. Integration would involve feeding the stored option metrics into eqats’ risk‑engineering subsystem for limit checks, VaR, margin calculations, etc.

## Integration Steps for eqats
1. **Environment Setup**
   - Clone the repo into `vendor/nse-options-last-5-years` or add as a submodule.
   - Create a virtual environment and install `requirements.txt`.
   - Ensure PostgreSQL is accessible; optionally use the provided `schema.sql` to create the `option_metrics` table.
2. **Data Ingestion**
   - Run the download scripts to populate `bhavcopy/raw/`, `yahoo_finance/`, `interest_rates/`, and `earning_dates/`.
   - Optionally schedule these scripts via cron or Airflow for daily updates.
3. **Enrichment & Storage**
   - Execute `process_data.py` to generate the JSON snapshot, **or**
   - Run `cd store_in_db && python store_s.py` to perform a multithreaded ETL that upserts enriched records into PostgreSQL.
   - Tune `BATCH_SIZE`, `MAX_WORKERS`, `STATEMENT_TIMEOUT` via environment variables to match eqats’ infrastructure.
4. **Consumption in eqats**
   - **Option A (Direct DB):** Have eqats’ data‑layer query the `option_metrics` table (JSONB column) for the latest IV, RV, Greeks, IVP/IVR per symbol/expiry/strike.
   - **Option B (File‑based):** Point eqats to `processed_data/processed_data.json` for batch‑mode back‑testing or research.
5. **Feature Usage**
   - Use the Greeks and IV term‑structure for volatility‑surface construction.
   - Leverage IV percentile/rank as a signal‑pre‑filter in eqats’ strategy module.
   - Feed realised volatility (Yang‑Zhang) into risk‑models for historical volatility estimates.
6. **Operational Considerations**
   - Monitor ETL logs for retries; the `store_s.py` script already implements automatic retries on transient DB errors.
   - Adjust `PG_SSLMODE` and connection parameters via env‑vars to match eqats’ security policies.
   - The pipeline is CPU‑bound; scale `MAX_WORKERS` according to available cores.
7. **Testing & Validation**
   - Compare a sample of records from the JSON output with the DB to ensure fidelity.
   - Validate that IV calculations match the reference in `nse_options_formulae.pdf`.
   - Run unit tests on the enrichment functions if eqats wishes to embed them directly.

## Example Code Snippet (Python)
```python
import os
import psycopg2
import json

# Assuming the ETL has already loaded data into Postgres
dsn = os.getenv("PG_DSN", "dbname=eqats user=eqats password=secret host=localhost")
with psycopg2.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(\"\"\"\n            SELECT symbol, trade_date, strike_price,\n                   (metrics->'ce'->>'iv_30')::float AS iv_30_ce,\n                   (metrics->'pe'->>'delta')::float AS delta_pe\n            FROM option_metrics\n            WHERE trade_date >= CURRENT_DATE - INTERVAL '30 days'\n            ORDER BY trade_date DESC\n            LIMIT 1000;\n        \"\"\");
        rows = cur.fetchall()
        # rows can be fed into eqats’ signal/risk modules
        print(json.dumps([dict(r) for r in rows], default=str))
```

## Summary
The NSE Options Data Analysis Toolkit supplies robust data‑engineering capabilities—ingestion, enrichment, and storage of multi‑year options metrics—that can be plugged directly into eqats’ data layer. While it does not provide signal generation or risk‑control logic, its outputs (IV, RV, Greeks, IV percentile/rank) are ideal inputs for eqats’ Signal & Execution and Risk Engineering subsystems. By adopting the provided ETL scripts or the JSON snapshot, eqats gains a reliable, production‑grade source of NSE options analytics without reinventing the wheel.
