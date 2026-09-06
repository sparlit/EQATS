# Integration Blueprint: Live‑NSE‑Stock API into eqats

## Overview
The Live‑NSE‑Stock repository offers a lightweight Node.js service that returns live NSE equity prices via a GET request (`?symbol=INFY`). It can be leveraged as a real‑time market‑data feed for the eqats trading system.

## Data Engine Integration
1. **Endpoint Wrapper** – Create a thin adapter in eqats’ data‑engine layer that calls `http://live-nse.herokuapp.com/?symbol=<SYMBOL>` (or a self‑hosted instance) for each subscribed instrument.
2. **Polling Scheduler** – Use eqats’ existing scheduler (e.g., cron‑based or event‑loop) to poll the API at a configurable interval (e.g., 1 second) to capture tick‑by‑tick prices.
3. **Normalization** – Map the JSON response (expected fields: `symbol`, `price`, `timestamp`, etc.) to eqats’ canonical market‑data schema.
4. **Persistence** – Store the normalized ticks in eqats’ timeseries database (e.g., InfluxDB or TimescaleDB) for downstream analysis and backtesting.
5. **Failover & Caching** – Implement a local cache (Redis) to serve the last known price if the API is unavailable, and log errors for alerting.

## Signal & Execution Logic
The repository does not contain any signal generation or order‑execution capabilities. Consequently, eqats would continue to rely on its own strategy modules; the Live‑NSE‑Stock feed would simply supply the raw price stream that those strategies consume.

## Risk Engineering
No risk‑limits, position‑sizing, or monitoring features are present in this repo. Risk checks in eqats (e.g., max‑drawdown, VaR, exposure limits) would remain unchanged and would operate on the data ingested from this feed.

## Deployment Considerations
- **Self‑host**: Because the free Heroku instance may have usage limits, deploy the Node.js app on eqats’ internal infrastructure (Docker/Kubernetes) to guarantee uptime and scalability.
- **Security**: Restrict access to the internal API endpoint via service‑mesh policies or API gateway authentication.
- **Monitoring**: Export API latency and error rates to eqats’ observability stack (Prometheus + Grafana) to ensure data‑feed health.

## Summary
By treating Live‑NSE‑Stock as a market‑data ingestion node, eqats gains a reliable, low‑cost source of live NSE equity prices without altering its existing signal, execution, or risk‑management layers.