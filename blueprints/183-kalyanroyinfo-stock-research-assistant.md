# Integration Blueprint for eqats

## Overview
The stock-research-assistant repo demonstrates a complete, end‑to‑end AI‑powered research assistant built on Databricks Free Edition. Its architecture cleanly separates transactional user state (Lakebase) from analytical market data (Unity Catalog medallion) and couples them with an LLM‑driven agent via Foundation Model APIs. These patterns can be transplanted into the eqats project to enhance data ingestion, storage, semantic search, and agent‑based signal generation.

## Data Engine Integration
1. **Deployment & Governance** – Adopt Databricks Asset Bundles (DAB) to version‑control all resources (Lakebase, pipelines, jobs, apps) and enable reproducible `databricks bundle validate/deploy` workflows.
2. **Medallion Architecture** – Implement a Lakeflow Declarative Pipeline similar to the repo’s `bronze.py → silver.py → gold.py`:
   - Bronze: Auto Loader ingests raw market data (price ticks, fundamentals, news) from sources such as yfinance, Alpha Vantage, or custom RSS feeds into Unity Catalog volumes.
   - Silver: Apply cleaning, deduplication, and enrichment (e.g., sector mapping, adjusted close) using Spark SQL/materialized views.
   - Gold: Build aggregated tables (daily OHLCV, volatility, notable‑move flags) and context chunks optimized for downstream AI Search.
3. **Transactional State** – Provision a Lakebase Postgres instance to store eqats‑specific user data: watchlists, portfolios, trade logs, notes, and risk parameters. Use the provided `schema.sql` as a starting point and manage credentials via Databricks OAuth/service principals.
4. **AI‑Powered Search** – Create an AI Search endpoint with a Delta Sync Index on the gold layer (price aggregates + context chunks). This enables semantic retrieval of market‑condition descriptions, similar to the repo’s “what changed since I last looked” feature.
5. **Orchestration** – Schedule ingestion jobs (market‑open/close) using the Databricks Jobs API (`spark_python_task` with serverless compute) to pull fresh data via yfinance or other providers, mirroring the two‑cron schedule in the repo.

## Signal & Execution Logic Integration
- **Agent Framework** – Replicate the agent’s tool‑calling loop:
  - Use Foundation Model APIs (Llama 3.3 70B or a comparable model) with an OpenAI‑compatible chat completion endpoint.
  - Implement hand‑rolled tools mirroring those in the repo: price/fundamentals summarizer, semantic news retriever, ticker comparator, note taker, watchlist manager, and a “delta‑since‑last‑look” tool that queries the AI Search index for changes.
  - The loop can be triggered on demand (via a Databricks App or webhook) or scheduled to produce daily signal reports.
- **Signal Generation** – Although the repo does not execute orders, its agent output (e.g., sentiment scores, anomaly flags, comparative rankings) can be fed into eqats’ existing signal engine as additional features or as a overlay for strategy validation.
- **Execution Hook** – Expose the agent’s conclusions through a REST endpoint or Databricks Webhook that eqats’ execution layer can subscribe to, translating insights into orders via the existing OMS.

## Risk Engineering Integration
- The current repository lacks explicit risk‑limits, position sizing, or real‑time risk monitoring. To add risk engineering capabilities:
  - Extend the Lakebase schema with risk‑limit tables (max exposure per sector, VaR limits, drawdown thresholds).
  - Implement a Databricks Job that reads the gold layer and user portfolio from Lakebase, computes risk metrics (portfolio VaR, concentration, leverage) and writes alerts to a monitoring table.
  - Hook these risk checks into the agent as a tool (e.g., “check‑risk‑limits”) so the LLM can refuse or adjust trade ideas that violate limits.
  - Visualize risk metrics in the Databricks App (Streamlit) alongside the existing watchlist and notes UI.

## UI & Presentation
- Deploy a Databricks App (Streamlit) that re‑uses the repo’s `app.py` structure:
  - Login via the app’s service principal, leveraging M2M OAuth.
  - Provide watchlist management, note‑taking, and a chat interface powered by the same agent.
  - Add eqats‑specific panels for portfolio performance, risk analytics, and order tickets.

## Deployment Steps
1. `databricks auth login --host <workspace-url> --profile <profile>`
2. `databricks bundle validate -t dev --profile <profile>`
3. `databricks bundle deploy -t dev --profile <profile>`
4. Run the one‑time `setup/bootstrap_catalog.sql` to create Unity Catalog schemas and Lakebase roles.
5. Trigger the ingestion jobs manually or let the cron schedule (09:15 & 15:30 IST) populate the medallion layers.
6. Launch the Databricks App to start interacting with the agent.

By integrating these patterns, eqats gains a robust, governed data pipeline, a scalable semantic search layer, and an LLM‑driven research assistant that can generate actionable insights while keeping transactional state secure and auditable.