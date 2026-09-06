# Integration Blueprint for SecurityWiseNSEData into eqats

## Repository Overview
The `SecurityWiseNSEData` project provides a curated, regularly updated dataset of NSE security‑wise equity Bhav data. It includes delivery volume information and is limited to the equity series SM, BE, BZ, EQ, ST, SZ, and BL. The data is sourced from the latest `BhavData` files and is maintained as a comprehensive, consistent source for equity market analysis.

## Data Engine Integration

### 1. Ingestion Pipeline
- **Source**: NSE BhavData files (daily equity bhav).
- **Process**: Pull the latest files, parse CSV/zip, filter rows where `Series` ∈ {SM, BE, BZ, EQ, ST, SZ, BL}.
- **Output**: A unified table/security‑wise file containing columns such as `Symbol`, `Series`, `Delivery Volume`, `Open`, `High`, `Low`, `Close`, `Turnover`, etc.

### 2. Storage & Versioning
- Store the filtered dataset in a partitioned format (e.g., Parquet by date or symbol) within eqats’ data lake.
- Maintain update timestamps to enable incremental loads; the existing automation can be hooked into eqats’ scheduler (e.g., Airflow, Prefect).

### 3. Usage in eqats
- **Feature Engine**: Delivery volume and other bhav fields can be used as raw inputs for factor construction (e.g., delivery‑to‑turnover ratio, volume‑weighted price).
- **Research**: The series‑filtered universe ensures analysis stays within liquid equity contracts, eliminating derivatives or debt series.
- **API**: Expose the dataset via eqats’ data service layer so strategies can query latest bhav data on demand.

## Signal & Execution Logic
The repository does not contain any signal generation, strategy logic, or order execution components. Consequently, there are no direct features to map into eqats’ signal & execution domain. If desired, the bhav data can serve as an upstream data source for eqats’ existing signal modules.

## Risk Engineering
No risk‑limit, position‑sizing, or risk‑monitoring utilities are present in the repository. Risk‑related calculations (e.g., volatility, VaR) would need to be built separately in eqats using the ingested bhav data as a market‑data feed.

## Future Enhancements (as indicated in the README)
- **Stock split, bonus, dividend data**: Once added, these corporate‑action fields can be integrated into eqats’ adjustment pipeline to ensure price and volume series are correctly back‑adjusted.

## Implementation Steps
1. Add a new ingestion job in eqats’ data‑engine that mirrors the existing automation (pull NSE BhavData, filter series).
2. Persist the output to eqats’ data lake under `market_data/nse/bhav/security_wise/`.
3. Update eqats’ data catalog to expose the new tables/views.
4. Adjust any factor‑creation scripts to reference the new delivery‑volume columns.
5. (Optional) Extend the pipeline to incorporate upcoming corporate‑action data when available.

## Conclusion
The core value of `SecurityWiseNSEData` lies in its reliable, series‑filtered NSE equity bhav dataset. By plugging its ingestion and storage logic into eqats’ data‑engine layer, eqats gains a high‑quality, up‑to‑date market‑data foundation for equity‑focused research and strategy development, while signal, execution, and risk modules remain unchanged pending future extensions.