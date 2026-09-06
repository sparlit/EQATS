# Integration Blueprint for eqats

## Overview
The mapsx/nse repository provides a fully automated pipeline that pulls quarterly financial results for the NIFTY‑500 universe from the NSE via the NseIndiaApi wrapper, extracts key line‑items (Revenue, Net Profit, EPS, Tax, Other Income) and publishes a JSON file to GitHub. This data can be consumed directly by any downstream analytics or trading system.

## Data Engine Features to Adopt
- **Scheduled Ingestion**: GitHub Actions workflow (`nse-update.yml`) runs every 6 hours at minute 17, invoking `collector.py`.
- **Unified API Access**: Uses the maintained `NseIndiaApi` Python package to call `results_comparison()` for each of the 500 companies and to fetch filing metadata and XBRL links.
- **Best‑effort XBRL Parsing**: When XBRL is available, the collector attempts to pull Tax and Other Income; missing fields are left as null rather than fabricated.
- **Robust Error Handling**: On transient request failures the pipeline preserves the last successful `results.json`, preventing data gaps.
- **Version‑controlled Storage**: The output `data/results.json` is committed back to the repository, providing a immutable, auditable history and enabling raw‑GitHub consumption (`https://raw.githubusercontent.com/<user>/<repo>/main/data/results.json`).
- **Lightweight Frontend**: `index.html` + `config.js` demonstrate how a dashboard can read the JSON directly from GitHub raw, requiring no backend server.

## Signal & Execution Logic
The repository does **not** contain any signal generation, strategy logic, or order‑execution components. It is strictly a data‑feeder. To use the data in eqats, you would combine this feed with your own signal‑generation modules (e.g., factor models, event‑driven triggers) that ingest the published JSON.

## Risk Engineering
No risk‑limits, position‑sizing, or risk‑monitoring features are present. Risk controls would need to be added in the eqats layer that consumes the data (e.g., volatility‑based position sizing, sector‑exposure caps).

## Integration Steps for eqats
1. **Fork or clone** the mapsx/nse repo into your eqats infrastructure (or mirror it via a GitHub Action that pushes to a private repo).
2. **Adjust the workflow** (`nse-update.yml`) to run on your preferred schedule (e.g., every 4 hours) and to push results to a private repository or an internal artifact store.
3. **Modify collector.py** (if needed) to output additional fields required by eqats (e.g., segment‑level revenue, contingent liabilities) by extending the XBRL parsing logic.
4. **Consume the JSON** in your eqats data‑engine: either pull directly from the raw GitHub URL (if you accept public exposure) or pull from your private repo’s releases/artifacts.
5. **Validate schema** upon ingestion (e.g., using Pydantic) to ensure required fields exist and flag missing data.
6. **Feed the cleaned dataset** into your signal‑generation pipelines (e.g., compute earnings surprises, revisions, tax‑rate changes) and into your risk‑engine for exposure checks.
7. **Monitor** the GitHub Actions run status; set up alerts on workflow failures to guarantee data freshness.

## Example Snippet (Python)
```python
import requests, pandas as pd
URL = \"https://raw.githubusercontent.com/your_eqats_repo/main/data/results.json\"
data = requests.get(URL, timeout=10).json
df = pd.json_normalize(data)  # each row = company
# Example signal: earnings surprise vs. estimate
if 'netProfit' in df.columns and 'netProfitEstimate' in df.columns:
    df['surprise'] = (df['netProfit'] - df['netProfitEstimate']) / df['netProfitEstimate'].abs()
```

## Benefits
- **Zero‑maintenance data source**: The pipeline handles authentication, rate‑limiting, and retry logic via NseIndiaApi.
- **Auditability**: Every commit to `results.json` is versioned, allowing rollback and historical analysis.
- **Low latency**: Data is available within minutes of the NSE filing, supporting near‑real‑time fundamental strategies.
- **Decoupled architecture**: No need to run a persistent NSE‑connected server; the data lives in GitHub and is consumed via HTTP.

## Caveats
- Relies on an **unofficial** NSE wrapper; monitor for breaking changes if NSE updates its endpoints.
- Tax and Other Income are only present when XBRL is parsable; plan for missing values in downstream models.
- The solution is designed for public consumption; for sensitive strategies consider hosting the repo privately or using GitHub Packages/Artifacts.
