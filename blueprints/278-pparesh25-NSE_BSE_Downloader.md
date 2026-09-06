# Integration Blueprint for eqats

## Overview
The NSE_BSE_Downloader provides a robust, production‑grade pipeline for acquiring and normalising Indian equity and derivative market data. Its core strengths lie in reliable ingestion, date‑aware source selection, corporate‑action adjustment, and immutable audit capabilities. These capabilities can be leveraged by eqats to build a trusted market‑data foundation for strategy research, execution, and risk management.

## Proposed Integration

### 1. Data Engine Enhancement
- **Unified Ingestion Module**: Wrap the downloader’s exchange‑segment logic (NSE Equity/Futures/SME/Index, BSE Equity/Index) as a pluggable data‑source adapter within eqats’ data‑engine layer. Expose a common interface `fetch_segment(date, segment)` that returns a DataFrame with the standardized nine‑column layout (including `TURNOVER` and `PREV_CLOSE`).
- **Date‑Aware URL Selection**: Reuse the logic that switches between legacy and current report eras to automatically handle historical data requests without manual curation.
- **Delivery & Open‑Interest Enrichment**: Automatically merge delivery quantity/percentage and futures OI change into the cash‑market files, providing eqats with richer fundamental fields for factor construction.
- **Symbol‑wise History Storage**: Store adjusted symbol histories (splits, bonuses, consolidations) in the `NSE/SYMBOLS/` and `BSE/SYMBOLS/` directory structure, enabling eqats to retrieve continuous price series for back‑testing without re‑applying adjustments.
- **Corporate‑Action Adjustment Pipeline**: Integrate the adjustment engine as a pre‑processing step that runs after download, ensuring all downstream signals operate on adjusted series while preserving the raw bhavcopy for audit.
- **Audit Mode (`--audit`)**: Expose a read‑only verification command that eqats can schedule (e.g., nightly) to validate digests, row counts, and schema consistency of the data lake, triggering alerts on corruption.
- **Schema‑Driven File Reading**: Leverage the per‑segment `SCHEMA.json` files to dynamically infer column widths, allowing eqats to read historical files of varying widths without hard‑coding column positions.
- **Calendar & Holiday Integration**: Use the IST‑aware trading‑date generator and cached NSE holiday calendar to align eqats’ trading‑day loops, ensuring that back‑tests and live runs respect market closures.
- **Cooperative Stop/Close**: Adopt the atomic‑file‑replacement pattern and cooperative cancellation semantics for eqats’ own long‑running data‑update workers, guaranteeing that partial writes never corrupt the data lake.

### 2. Signal & Execution Logic (No Direct Mapping)
The downloader does not contain signal generation or order‑execution code. However, the cleaned, adjusted data it provides can be consumed by eqats’ existing signal modules. Integration points:
- Feed the adjusted symbol histories into eqats’ feature‑engine to compute technical/fundamental signals.
- Use the normalized turnover and previous close as inputs for liquidity‑adjusted execution algorithms.
- Leverage the delivery‑quantity metrics for short‑term supply‑demand signals.

### 3. Risk Engineering (No Direct Mapping)
Risk‑limit checks, position sizing, and real‑time monitoring are outside the scope of the downloader. eqats can continue to use its own risk engine, feeding it the clean market data supplied by the integrated downloader.

## Implementation Steps
1. Fork the NSE_BSE_Downloader repo (or add it as a submodule) and isolate the core download/adjustment logic into a Python package `nse_bse_loader`.
2. Define an eqats adapter that implements `eqats.data.sources.NSEBSESource` using the package’s public functions.
3. Add a configuration section in eqats’ YAML to toggle exchanges, date ranges, and audit scheduling.
4. Write unit tests that compare the adapter’s output against known sample bhavcopy files.
5. Schedule the `--audit` mode via eqats’ monitoring cron to emit health‑checks to logging/metrics.
6. Document the data‑lake layout (`~/NSE_BSE_Data/`) and ensure eqats’ data‑ingestion points point to this directory.

## Benefits
- **Reliability**: Proven retry, atomic replacement, and cooperative shutdown reduce data‑corruption risk.
- **Historical Depth**: Automatic era‑switching enables seamless access to multi‑year NSE/BSE archives.
- **Adjustment Consistency**: Corporate‑action adjustments are applied uniformly, guaranteeing continuous price series for strategy research.
- **Operational Transparency**: Audit mode provides immutable verification without altering stored data.
- **Reduced Development Effort**: Re‑using a mature, tested downloader frees eqats to focus on signal generation, execution, and risk.

## Open Considerations
- Ensure licensing compatibility (GPL‑3.0) with eqats’ own license; if needed, contact the author for a commercial exception or re‑implement core logic under a compatible license.
- Monitor upstream changes to NSE/BSE report formats and adapt the downloader’s URL‑parsing logic accordingly.
- Consider extending the downloader to include commodity or currency segments if eqats expands beyond equities.

---
*This blueprint maps the most valuable data‑engine features of NSE_BSE_Downloader onto the eqats architecture, leaving signal‑execution and risk‑engineering domains to be supplied by eqats’ existing components.*