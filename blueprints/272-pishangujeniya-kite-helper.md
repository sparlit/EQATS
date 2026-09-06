# Integration Blueprint: kite-helper → eqats

## Overview
kite-helper is a Dockerized C#/ASP.NET Core web application that enables users to download historical per‑minute Indian NSE/BSE stock data from the Kite (Zerodha) API and save it as CSV files locally. It provides a simple UI for symbol selection, date range, and timeframe configuration.

## Data Engine Integration
- **Ingestion Adapter**: Wrap the kite-helper container as a micro‑service that eqats can invoke via its HTTP endpoint (the app runs on port 80). eqats can POST a job payload (symbols, start/end dates, interval) and receive a CSV file or a download link.
- **Storage Hook**: Instead of relying on the UI‑driven local save, modify the container to expose an API endpoint that streams the CSV back to the caller, allowing eqats to store the data directly into its data lake (e.g., Amazon S3, Azure Blob, or local NAS) under a versioned folder structure (`data/raw/indian/minute/<symbol>/<YYYY-MM-DD>.csv`).
- **Scheduler**: Use eqats’ orchestration layer (e.g., Airflow, Prefect, or a simple cron) to trigger the kite-helper service at the desired frequency (daily after market close) to refresh the minute‑bar universe.
- **Metadata**: Augment the CSV with eqats‑required headers (timestamp, open, high, low, close, volume) and add a metadata JSON sidecar containing source ("kite-helper"), download timestamp, and request parameters.

## Deployment
1. Pull the existing image: `docker pull pishangujeniya/kite-helper`.
2. Deploy alongside eqats services in the same Docker network or Kubernetes namespace.
3. Expose only the internal API port (e.g., 8080) to eqats; keep the UI port firewalled if not needed.
4. Configure environment variables for Kite API credentials (api_key, access_token) – eqats can inject these via secrets management (Vault, Kubernetes secrets) to maintain the "privacy-first" principle.

## Usage Example (pseudo‑code)
```python
import requests, pandas as pd, json

def fetch_indian_minute(symbol, start, end):
    resp = requests.post(
        "http://kite-helper:80/api/download",
        json={"symbol": symbol, "from": start, "to": end, "interval": "1min"},
        auth=("user", "pass")  # if basic auth is added
    )
    resp.raise_for_status()
    df = pd.read_csv(resp.content)
    return df

# eqats pipeline step
data = fetch_indian_minute("RELIANCE.NS", "2024-08-01", "2024-08-31")
data.to_parquet("s3://eqats-lake/raw/indian/minute/RELIANCE.NS/2024-08.parquet")
```

## Considerations
- **Rate Limits**: Kite API imposes request limits; eqats should batch requests and respect the limits, possibly using kite-helper’s built‑in throttling or adding a proxy layer.
- **Authentication**: The original app expects manual login via UI; for headless operation eqats must supply credentials programmatically (e.g., via Kite’s `generate_session` flow). This may require extending kite-helper or wrapping it with a small auth‑handler script.
- **Data Validation**: After download, eqats should validate CSV schema and check for missing bars before persisting.
- **Licensing**: kite-helper is open source; ensure compliance with its license when redistributing or modifying.

## Summary
By treating kite-helper as a containerized data‑engine service, eqats can reliably acquire high‑resolution Indian equity market data without building a custom Kite API client, while preserving the original tool’s privacy‑first, local‑control ethos.
