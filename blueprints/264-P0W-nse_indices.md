# Integration Blueprint: nse_indices into eqats

## Overview
The `nse_indices` repository provides a Python‑based pipeline for fetching, storing, and analysing NSE thematic and strategy indices (e.g., Nifty India Defence, Nifty SME Emerge). It calculates long‑term performance (CAGR) and outputs the top constituents that can be turned into a tradable basket.

## Data Engine Integration
1. **Ingestion** – Replace the existing scraper with eqats’ unified data‑ingest adaptor. The script currently pulls index constituent lists and historical levels from the NSE website; eqats can expose this as a `NSEIndexFetcher` connector.
2. **Storage** – Instead of writing raw CSV/JSON to a local `data/` folder, route the outputs to eqats’ feature store (e.g., Parquet on S3 or Delta Lake). The existing file‑write calls can be wrapped by eqats’ `store_artifact` utility.
3. **Derived Metrics** – The CAGR and rolling return calculations can be exposed as eqats feature‑engineering transforms, making them available downstream for signal generation.

## Signal & Execution Logic Integration
1. **Basket Signal** – The logic that selects the top 10‑15 stocks by weight/market cap can be turned into an eqats signal module (`nse_indices_basket_signal`). It will consume the stored constituent features and emit a target‑weight vector.
2. **Rebalancing Schedule** – The repository notes semi‑annual (Defence) and quarterly (SME Emerge) rebalancing. eqats’ scheduler can trigger the signal module at those frequencies, producing orders for the broker or Smallcase adapter.
3. **Order Execution** – The generated target weights can be fed into eqats’ execution engine (e.g., via the `ExecutionAdapter` for broker APIs or Smallcase) to create/rebalance the basket.

## Risk Engineering Considerations
The source repo does not contain risk‑management components (volatility scaling, VaR limits, position‑size caps). When integrating, eqats should overlay its standard risk layer:
- Apply portfolio‑level volatility targeting.
- Enforce max‑position and sector‑concentration limits.
- Add pre‑trade compliance checks and post‑trade monitoring.

## Implementation Steps
1. Fork `nse_indices` into the eqats monorepo under `contrib/nse_indices`.
2. Replace direct `requests`/`BeautifulSoup` calls with eqats’ `DataFetcher` interface.
3. Change file writes to `eqats.store_artifact(path, df, format='parquet')`.
4. Export a function `get_top_constituents(index_name, lookback_days)` returning a DataFrame of weights.
5. Create a signal class `NSEIndicesBasketSignal` that calls the above and outputs a signal compatible with eqats’ signal bus.
6. Register the signal with eqats’ scheduler using cron expressions `0 0 1 */6 *` (semi‑annual) and `0 0 1 */3 *` (quarterly).
7. Wire the signal output to the desired execution adapter (Broker or Smallcase).
8. Add unit tests that mock the NSE endpoints and verify the basket composition.

## Expected Outcome
Integrating `nse_indices` will give eqats a ready‑made, data‑driven thematic‑index basket (Defence and SME Emerge) with transparent rebalancing rules, expanding the strategy library while relying on eqats’ robust data, execution, and risk infrastructure.