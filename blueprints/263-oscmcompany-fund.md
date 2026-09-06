# Integration Blueprint for oscmcompany/fund into eqats

## Overview
The fund repository provides a Rust‑based training and trading platform that relies on PostgreSQL for market data storage, S3 for a bar archive, DuckDB for ad‑hoc querying, and a pg_cron‑driven event loop for signal generation and execution. These components can be mapped onto the eqats domains as follows.

## Data Engines
- **PostgreSQL storage** – Ingest ticker metadata and historical bars via the `data:seed:postgres` task; eqats can reuse this ingestion pipeline to populate its relational market‑data store.
- **S3 bar archive** – Seed raw bar data with `data:seed:s3`; eqats can treat the S3 bucket as its data lake, enabling cheap long‑term storage and versioned datasets.
- **DuckDB query interface** – Launch DuckDB with `start-duckdb <profile>` to query S3‑backed views locally; eqats could expose a similar ad‑hoc SQL layer for analysts and back‑testing.
- **Seeding automation** – Both seeding tasks are invoked through `devenv tasks run`, showing a reproducible, version‑controlled data‑onboarding process that eqats can adopt.

## Signal & Execution Logic
- **Event‑loop service** – The `fund` binary is a single event loop awakened by PostgreSQL `LISTEN/NOTIFY` triggered by pg_cron; eqats can replace its internal scheduler with a PostgreSQL‑notify driven loop to decouple strategy evaluation from fixed‑time ticks.
- **Training cron** – Model training runs weekdays at 23:00 UTC (`train-tide-model.log`); eqats can schedule its own model‑training jobs via cron or pg_cron, ensuring artifacts are ready before the trading session.
- **Dashboard** – A web UI served on port 8084 provides real‑time visibility; eqats could embed a similar lightweight dashboard (e.g., using Rust + Actix or Axum) for monitoring positions, signals, and risk metrics.
- **Git‑sync** – Automatic updates every minute keep the VM code current; eqats can implement a similar side‑car process that pulls the latest strategy code from a Git repo on each node.

## Risk Engineering
The README does not describe explicit risk‑limit, position‑sizing, or monitoring mechanisms. Consequently, there are no directly transferable risk‑engineering features to integrate at this time; eqats would need to supply its own risk controls (e.g., VaR limits, max‑drawdown checks) around the borrowed execution core.

## Implementation Steps
1. **Data layer** – Provision a PostgreSQL instance and an S3 bucket; run the existing seeding scripts (or adapt them) to load ticker metadata and historical bars.
2. **Query layer** – Deploy DuckDB locally or as a service, pointing it at the S3 bucket to reproduce the `start-duckdb` workflow for exploratory analysis.
3. **Execution core** – Replace eqats’ current timer‑driven loop with a PostgreSQL listener that wakes on `NOTIFY` from a pg_cron job that ticks at the desired frequency (e.g., every minute).
4. **Model training** – Add a cron entry (or pg_cron schedule) that runs the training pipeline at 23:00 UTC, persisting artifacts to S3 for consumption by the execution loop.
5. **Observability** – Stand up a simple HTTP dashboard (port 8084) showing live signals, positions, and logs; hook into the existing log files (`/var/log/fund/*.log`) or integrate with a logging framework.
6. **Code synchronization** – Deploy a lightweight sync daemon that `git pull`s the strategy repository every minute, mirroring the `git sync` behavior described in the README.
7. **Testing** – Validate end‑to‑end flow by seeding a small dataset, triggering a `NOTIFY`, and confirming that the event loop processes the signal, updates the dashboard, and respects any risk limits added later.

By adopting these patterns, eqats can leverage a battle‑tested, Rust‑based infrastructure while retaining flexibility to plug in its own signal generation and risk‑management logic.