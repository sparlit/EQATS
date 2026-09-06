# Integration Blueprint: Swadeshi Tracker -> eqats

## Overview
The Swadeshi Tracker repo builds a weekly-updated registry of Indian-vs-foreign ownership for ~270 companies (listed + private) and serves it as a single-page static site. The core value for eqats is the alternative ownership dataset that can be used as a factor, screen, or risk monitor for Indian equities.

## Data Engine Features to Adopt
1. Ingestion Pipeline – Reuse scripts/refresh.py (or a Python equivalent) to pull NSE XBRL filings on a schedule (e.g., weekly cron). The script:
   - Downloads each listed company’s latest quarterly shareholding XBRL.
   - Parses the taxonomy to bucket holders as Indian or foreign (using the filing’s native Indian/foreign tags).
   - Applies ultimate-control overrides (e.g., Britannia promoter held via UK entity but controlled by Indian Wadia group).
   - Falls back to the previous entry if NSE is unreachable, marking it stale.
2. Static Data Store – The output site/registry.json is a simple JSON map of {company: {indian_pct, foreign_pct, brands[], stale?}}. This can be version-controlled or stored in eqats's data lake (e.g., S3, GCS) for fast lookup.
3. Hybrid Curated Data – Private-company entries live in data/companies.json with a static block and confidence scores. eqats can maintain a similar curation layer for unlisted entities.
4. Failure-Safe Mechanism – Implement the same 'keep last good value + stale flag' pattern to avoid data gaps when NSE throttles or returns errors.

## Signal & Execution Logic (None)
The tracker does not generate trading signals or execute orders. In eqats, the ownership percentages would be fed into existing signal modules (e.g., factor construction, sentiment scoring) rather than replacing them.

## Risk Engineering Applications
While the repo itself lacks risk limits, the ownership data can enrich eqats's risk engine:
- Foreign-Ownership Exposure: Compute portfolio-level foreign-ownership weight = sum(position value * foreign_pct). Use this as a risk factor to monitor regulatory or macro-exposure limits.
- Concentration Alerts: Flag stocks where foreign_pct exceeds a threshold (e.g., >50%) or where sudden changes in foreign_pct occur week-over-week.
- Liquidity & Governance Overlay: Combine with other governance metrics (promoter pledging, related-party transactions) for a composite governance risk score.
- Stress Testing: Simulate scenarios where foreign capital flows reverse (e.g., FII outflows) by adjusting foreign_pct assumptions.

## Integration Steps
1. Fork the ingestion script into eqats/data_engines/ownership/ directory, adapting it to write to eqats's preferred storage (e.g., Parquet dataset).
2. Add a schema for the ownership table: company_id, indian_pct, foreign_pct, as_of_date, stale_flag.
3. Create a daily/weekly Airflow or cron DAG that runs the script, validates output (basic checks: sums ~100%, no nulls for listed companies), and registers the new partition.
4. Expose a lookup service (e.g., a thin FastAPI endpoint or a broadcast variable) that eqats's strategy and risk modules can query to enrich instrument metadata.
5. Develop risk-engineering hooks:
   - In the risk-limits module, add a foreign-ownership limit check using the lookup.
   - In the signal factory, add an optional factor foreign_ownership_pct or delta_foreign_ownership_wow.
   - In the monitoring dashboard, plot time-series of aggregate foreign ownership for watch-lists.
6. Documentation & Governance – Mirror the repo's README style: explain data sources, update frequency, confidence levels for private companies, and the stale-data handling.

## Benefits
- Alternative Data Edge: Ownership structure is low-frequency but informative for regulatory risk, sentiment, and potential price pressure from FII flows.
- Zero-Cost Maintenance: The script uses only Python stdlib; no external dependencies, making it robust for eqats's infrastructure.
- Transparency: The classification logic is pure arithmetic based on filing tags—no black-box AI—aligning with eqats's emphasis on explainable models.

## Caveats
- Data refresh is weekly (aligned with NSE quarterly filings); intraday changes are not captured.
- Private-company entries rely on manual curation; confidence scores should be propagated to downstream models.
- The dataset covers only Indian-listed and major private firms; broader coverage would require additional sources (e.g., BSE filings, MCA).

*Integrating Swadeshi Tracker's ownership engine equips eqats with a transparent, regularly refreshed alternative data source for signal enrichment and risk monitoring.*