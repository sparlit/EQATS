# Integration Blueprint: India Sector Screener into eqats

## Overview
The india-sector-screener repository provides a lightweight, self-contained weekly sector analysis tool for the Indian equity market. It fetches price data from Yahoo Finance, computes sector performance, and outputs an HTML report. These capabilities can be leveraged within eqats to enhance Indian market coverage, generate sector‑rotation signals, and enrich the data engine.

## Data Engine Integration
1. Price Ingestion Adapter
   - Reuse the Yahoo‑Finance fetch logic (urllib/request + json) to pull daily OHLCV for the NSE/BSE ticker list.
   - Store the raw series in eqats’ market_data lake (e.g., Parquet partitioned by date/symbol) instead of a single data.json.
   - Add a validation step that mirrors the resolver’s “unresolved” ticker reporting to flag missing symbols.

2. Sector Constituent Mapping
   - Maintain a static mapping of ~278 stocks to the 21 sectors used by the screener (downloadable from the repo’s sectors.json‑like source).
   - Expose this mapping as a reference table in eqats for quick sector‑lookup during signal generation.

3. Automated Refresh
   - Adapt the GitHub Actions workflow (weekly-refresh.yml) to eqats’ CI: schedule a Sunday UTC job that runs the ingestion adapter, writes new partitions, and triggers downstream signal pipelines.
   - Reuse the existing check_output.py sanity check (ensuring all sectors have data) as a quality gate.

## Signal & Execution Logic
1. Sector Return Signal
   - Compute median weekly return for each sector exactly as the screener does (median(constituent returns)).
   - Emit a ranked sector signal (long top‑N sectors, short bottom‑N) that can be fed into eqats’ signal aggregator.
   - Provide the “best‑performing share” per sector as an optional idiosyncratic alpha signal.

2. Universe‑Wide Movers
   - Calculate the biggest absolute movers across all stocks each week.
   - Use these as a short‑term reversal or momentum filter depending on strategy design.

3. Signal Format
   - Output signals in eqats’ canonical JSON schema: {date, sector, signal_type, value, confidence}.
   - Include metadata such as baseline_date, unresolved_tickers, and data_coverage_pct.

## Risk Engineering Considerations
- The screener does not contain risk controls; therefore, any sector‑rotation signal derived from it should be passed through eqats’ risk layer (position limits, sector concentration caps, volatility scaling).
- Add a post‑processing step that applies eqats’ risk engine to the raw sector scores (e.g., max sector weight, turnover constraints).

## Implementation Steps
1. Fork the screener’s Python scripts into eqats/contrib/india_sector_screener/.
2. Replace the data.json write with a function that writes to eqats’ data lake.
3. Create a thin wrapper (sector_signal.py) that calls the existing ranking logic and emits eqats‑compatible signals.
4. Add a unit test that validates the output against a known fixture (the example week printed in the README).
5. Register the new signal provider in eqats’ signal registry and schedule the ingestion job via the existing CI/CD pipeline.
6. Monitor the unresolved ticker count; if it exceeds a threshold, raise an alert in eqats’ monitoring dashboard.

## Benefits
- Immediate coverage of ~278 Indian equities with zero external dependencies.
- Ready‑to‑use weekly sector ranking signal that can be combined with other alpha models.
- Transparent, auditable pipeline (GitHub Actions) that eqats can adopt for its own data refreshes.
- Minimal maintenance: the upstream screener already handles ticker changes and logs unresolved symbols.

## Caveats
- The tool relies on Yahoo Finance, which may have delayed or missing data for certain Indian symbols; eqats should supplement with alternative data feeds where needed.
- No intraday or high‑frequency capability; suitable for low‑to‑medium frequency strategies only.
- No explicit risk metrics; risk management must be applied downstream in eqats.
