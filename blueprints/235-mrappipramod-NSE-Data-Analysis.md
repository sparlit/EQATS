# Integration Blueprint for eqats: NSE Fundamental Analysis Features

## Overview
The mrappipramod/NSE-Data-Analysis repository provides a pure fundamental‑analysis screener for NSE‑listed stocks. It fetches financial statements via yfinance, computes valuation, profitability, stability, growth, and intrinsic‑value scores, and exports results as JSON/CSV. These capabilities can be leveraged in eqats to generate fundamental‑based signals, enrich the data engine, and optionally inform risk assessments.

## Data Engine Integration
- **Unified Data Fetcher**: Replace eqats’ current market‑data adapter with the repository’s `utils/data_fetcher.py`. The abstract `DataSource` interface allows plugging in yfinance (default) or any licensed NSE/BSE feed without changing downstream logic.
- **Robust Ingestion**: Built‑in retry with exponential backoff, jittered delays, and per‑symbol error isolation prevents a single bad ticker from aborting a batch run.
- **Disk‑Based Cache**: Runtime parquet cache (`data/cache/`) reduces repeated yfinance calls; eqats can adopt a similar cache layer to mitigate rate‑limits when scanning large universes (e.g., Nifty 500).
- **Universe Management**: Live fetch of Nifty 500 constituents from NSE Indices with a static fallback (`data/nifty500_fallback.csv`) ensures resilience; eqats can reuse this logic for its own watchlist loaders.
- **Export Pipeline**: The `scripts/export_daily.py` headless script and GitHub Action (`daily_export.yml`) demonstrate automated daily JSON/CSV exports that eqats could schedule to feed downstream systems or visualisation tools.

## Signal & Execution Logic Integration
- **Five‑Pillar Scoring Engine**: The `utils/scoring_engine.py` computes a 0‑100 composite score across Valuation, Profitability, Stability, Growth & Trend, and Valuation Upside. eqats can treat each pillar as an independent factor model or combine them into a single fundamental signal.
- **Valuation Models**: Two‑stage DCF on free cash flow, Graham Number, and relative valuation (sector‑median PE/PB) are implemented in `utils/valuation.py`. These provide intrinsic‑value estimates that eqats can use to generate “undervalued/overvalued” signals.
- **Peer Comparison & Percentile Ranking**: `utils/peer_comparison.py` calculates sector medians and percentile ranks, enabling eqats to produce relative‑value signals (e.g., rank within sector).
- **Signal Output Format**: The `utils/exporter.py` converts results into a standardized JSON/CSV schema that eqats can ingest directly, facilitating rapid prototyping of fundamental‑based strategies.
- **Headless Execution**: Running `scripts/export_daily.py` yields a ready‑to‑consume signal feed; eqats could invoke this script as a pre‑trade signal generator or integrate its functions into the signal‑generation microservice.

## Risk Engineering Integration
- **Explicit Risk Limits**: The repository does not contain position‑sizing, risk‑limit, or real‑time risk‑monitoring modules.
- **Stability Metrics as Risk Proxies**: The Stability pillar (Debt/Equity, Current Ratio, Quick Ratio) captures balance‑sheet strength. eqats could repurpose these metrics as inputs to its risk engine (e.g., leverage‑based risk adjustments) or use them to filter out high‑risk universes before signal generation.
- **Extensibility**: Because the data fetcher is abstracted, eqats could swap in a licensed data source that provides audited financials and real‑time updates, thereby improving the reliability of risk‑relevant fundamentals.

## Implementation Steps for eqats
1. **Adapter Layer**: Create a thin wrapper around `DataSource` that matches eqats’ market‑data interface, injecting the yfinance‑based fetcher (or a paid NSE feed) as needed.
2. **Cache Integration**: Adopt the parquet caching strategy (`data/cache/`) to store fundamentals per symbol with TTL, reducing API calls during batch scans.
3. **Signal Service**: Import `scoring_engine.compute_score`, `valuation.get_intrinsic_value`, and `peer_comparison.get_sector_rank` into eqats’ signal‑generation pipeline; map their outputs to eqats’ signal schema (e.g., `signal_type: fundamental`, `score`, `target_price`, `confidence`).
4. **Export Automation**: Mirror the `export_daily.py` script and GitHub Action to produce daily fundamental signal files that eqats’ execution layer can subscribe to.
5. **Risk‑Filter Module**: Build a pre‑trade filter that flags stocks with Debt/Equity > threshold or Current Ratio < threshold, using the same stability calculations from the repository.
6. **Testing & Validation**: Start with a Nifty 50 run to verify latency and correctness, then scale to Nifty 500; compare exported JSON/CSV against eqats’ existing signal formats to ensure compatibility.

## Expected Benefits
- **Fundamental Depth**: Instant access to multi‑year growth trends, DCF‑based intrinsic value, and sector‑relative valuation without building these models from scratch.
- **Robust Data Handling**: Proven retry/backoff, caching, and fault‑isolated ingestion reduces downtime and API‑blocking risks.
- **Reproducible Exports**: Automated daily commits of JSON/CSV provide a version‑controlled signal archive for backtesting and audit trails.
- **Modular Extensibility**: The abstract data‑source design simplifies swapping yfinance for institutional‑grade feeds when eqats requires higher reliability or real‑time data.

## Caveats
- The screener relies on yfinance, which has no SLA and may miss data for banks/NBFCs or newly listed firms; eqats should monitor failure logs and consider fallback data sources for critical universes.
- The DCF and Graham Number use generic assumptions (11% discount rate, 4% terminal growth); eqats may want to calibrate these parameters per‑sector or per‑strategy.
- No explicit execution or order‑management logic is present; integration focuses solely on data and signal generation.
