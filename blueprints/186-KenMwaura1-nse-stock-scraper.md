# Integration Blueprint for eqats: NSE Stock Scraper Features

## Overview
The `nse-stock-scraper` repository provides a robust pipeline for ingesting live Nairobi Stock Exchange (NSE) prices, persisting them in MongoDB, and triggering SMS alerts based on price thresholds. These capabilities can be leveraged within the eqats project to enhance data acquisition, signal generation, and risk monitoring for African equities.

## Data Engines Integration
- **Market Data Ingestion**: Replace or supplement eqats' current data feeds with the Scrapy-based scraper (`afx_scraper`) that pulls real‑time ticker, price, and change from the AFX website (https://afx.kwayisi.org/nseke/). The scraper yields structured items that can be fed directly into eqats' ingestion layer.
- **Storage Layer**: Utilize the existing PyMongo integration to write scraped records into a MongoDB Atlas collection (default `nse_data`). eqats can map this collection to its market‑data store, benefiting from the unique index that prevents duplicate timestamps.
- **Containerized Deployment**: Adopt the provided `docker-compose.yml` to run the scraper alongside a MongoDB service, ensuring reproducible environments. eqats can incorporate this service into its development stack or use the Docker image for production pipelines.
- **Configuration Management**: Follow the `.env` pattern for MongoDB URI, database name, and Africa's Talking credentials, aligning with eqats' secret‑management practices.
- **Quality Assurance**: Reuse the GitHub Actions workflow (lint, security, test, build) to enforce code quality for any custom scraper extensions eqats may develop.

## Signal & Execution Logic Integration
- **Threshold‑Based Alerting**: The `stock_notification.py` script exemplifies a simple signal: query the latest stored price, compare against a configurable threshold (default 38 KES), and trigger an action. eqats can adapt this pattern to generate trading signals (e.g., buy/sell alerts) by replacing the SMS call with an order‑execution API.
- **Notification Execution**: The Africa's Talking SDK usage demonstrates how to send outgoing messages. eqats can wrap this in an execution module that routes signals to brokers, execution venues, or internal alerting systems (Slack, email, webhook).
- **Scheduler Integration**: The guide for Heroku Advanced Scheduler (or cron/Kubernetes Jobs) shows how to run the notification script at regular intervals (e.g., daily at 11:00 AM Nairobi time). eqats can adopt a similar scheduling mechanism for its signal generation jobs.
- **Extensibility**: The notification script is decoupled from the scraper; eqats can keep the ingestion and signaling layers separate, allowing independent scaling and testing.

## Risk Engineering Integration
- **Risk Threshold Monitoring**: The price‑threshold check functions as a rudimentary risk limit (e.g., flag when a stock exceeds a certain level). eqats can extend this to multiple risk metrics (volatility, exposure, concentration) by evaluating stored market data.
- **Duplicate Prevention**: The unique index on (ticker, timestamp) ensures data integrity, reducing the risk of erroneous signals due to repeated records—a practice eqats should enforce in its own storage layer.
- **Observability**: Atlas Charts integration provides visual dashboards of price trends. eqats can replicate this with its own monitoring stack (Grafana, Kibana) to track data quality and signal frequency.
- **Alert Fatigue Mitigation**: By making the threshold configurable and allowing the notification script to be toggled, eqats can control alert frequency, a key risk‑management consideration.

## Implementation Steps for eqats
1. **Ingest**: Add the Scrapy spider as a new data‑source plugin; map its output to eqats' market‑data schema.
2. **Store**: Configure a MongoDB destination (or adapt to eqats' preferred store) using the same connection parameters; apply unique indexes.
3. **Signal**: Create a signal module that reads the latest market data, applies a user‑defined risk/threshold rule, and emits a signal object.
4. **Execute**: Implement an execution adapter that forwards the signal to the desired broker or notification channel (SMS, email, webhook), reusing the Africa's Talking code as a template.
5. **Schedule**: Deploy the signal module as a scheduled job (cron, Kubernetes CronJob, or managed scheduler) aligned with market hours.
6. **Monitor**: Set up dashboards and alerts on data latency, duplicate counts, and threshold breaches to satisfy risk‑oversight requirements.
7. **CI/CD**: Incorporate the existing GitHub Actions workflow (or adapt) to validate any changes to the scraper or signal code.

## Conclusion
By adopting the scraper’s ingestion pipeline, threshold‑based alerting, and containerized deployment practices, eqats can rapidly expand its coverage of African equities, improve data reliability, and automate risk‑aware notifications without building these components from scratch.
