# Integration Blueprint for eqats: NSE Feed Monitor

## Overview
The `nse-live_testing` repository provides a lightweight, cloud‑ready monitor for the NSE (National Stock Exchange) live feed. Built with JavaScript, Playwright, and GitHub Actions, it validates feed availability, data correctness, rendering stability, and mobile responsiveness, producing detailed Markdown/JSON reports and screenshots.

## Relevant Features for eqats

### Data Engines
- **Live feed ingestion validation** – Scripts fetch the NSE endpoint and confirm that the feed loads, populates, and updates correctly.
- **Data quality checks** – Verifies filter correctness, newest visible event, and event detail rendering, ensuring that the ingested market data meets expected schema and content.
- **Automated reporting** – Each run generates Markdown, JSON, and a mobile screenshot stored under `reports/` (or `uptime-reports/` for uptime checks), providing a structured audit trail of feed health.

### Signal & Execution Logic
- *No direct signal generation or order execution logic is present in this repository.*
  The monitor is purely observational; however, the validated feed data could be consumed by eqats’ strategy layer as a trusted market‑data source.

### Risk Engineering
- **Continuous uptime monitoring** – The `npm run uptime` script and the associated GitHub Actions workflow perform HTTP status checks, text‑marker validation, and failure detection every 5 minutes (via an hourly workflow that runs twelve sub‑checks).
- **Alerting via workflow failure** – If the feed stops responding correctly, the GitHub Actions job fails, triggering notifications (email, Slack, etc.) that can be hooked into eqats’ risk‑monitoring pipeline.
- **Historical health artifacts** – Reports are committed back to the repository (`reports/` folder) and also uploaded as workflow artifacts, enabling trend analysis and post‑mortem reviews.

## How to Integrate into eqats

1. **Adapt the fetch/validation scripts**
   - Extract the core Playwright‑based fetch logic (`npm run monitor`) into a reusable Node.js module that eqats can import.
   - Parameterize the target URL, expected markers, and validation rules so the same module can monitor multiple exchanges or data providers.

2. **Feed the validated data into eqats’ data engine**
   - After a successful monitor run, emit a JSON payload (already produced under `reports/`) to eqats’ ingestion pipeline (e.g., via a Kafka topic or internal message bus).
   - eqats can treat this payload as a “market‑data health flag” alongside raw tick data, allowing strategies to pause or switch data sources when health degrades.

3. **Leverage the uptime workflow for risk monitoring**
   - Copy the GitHub Actions uptime workflow into eqats’ CI/CD repo, adjusting the schedule to match eqats’ trading hours (e.g., 09:15–15:30 IST).
   - Use the workflow’s failure status to trigger eqats’ risk‑engine alerts (e.g., widen position‑size limits, halt new order submission) via an existing alert‑router.

4. **Reporting and audit**
   - Store the generated Markdown/JSON reports in eqats’ document store (e.g., S3 bucket with prefix `nse_monitor/`).
   - Build a simple dashboard (Grafana, Metabase) that reads these reports to visualize feed latency, error rates, and mobile‑render stability over time.

5. **Deployment considerations**
   - The monitor only requires Node.js ≥14 and Playwright; it can be run in a lightweight Docker container, making it easy to deploy alongside eqats’ existing services.
   - Ensure the container has network access to the NSE endpoint and can push artifacts to eqats’ storage backend.

## Benefits
- **Early detection of feed degradation** before it impacts strategy performance.
- **Standardized health artifacts** that feed directly into risk‑management dashboards.
- **Low‑cost, serverless execution** via GitHub Actions or any CI system, reducing operational overhead.

## Open Items
- Implement authentication/token handling if the NSE feed requires secured access.
- Extend validation to include latency measurements (round‑trip time) and publish them as metrics.
- Create a unified config schema so the same monitor can be reused for other data sources (BSE, MCX, etc.)
