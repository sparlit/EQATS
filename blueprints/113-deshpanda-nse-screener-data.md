# Integration Blueprint for nse-screener-data into eqats

## Overview
The nse-screener-data repository provides a rich collection of Indian equity market datasets sourced from NSE, SEC, and public filings. These datasets can be leveraged across eqats’ three domains: Data Engines for ingestion and storage, Signal & Execution Logic for alpha generation, and Risk Engineering for risk monitoring and limits.

## Data Engines
- **bhav/** – Daily OHLCV, volume, turnover, and delivery (shares kept overnight). Store as partitioned Parquet by date; apply corporate‑action adjustments from the main repo before return calculations.
- **futstk/** – Daily futures price and open interest (OI) with daily ΔOI. Ingest as time‑series tables; OI change signals futures positioning.
- **fr_xbrl/** – Quarterly XBRL profit numbers with exact public timestamps. Load into a fundamentals warehouse; the timestamp ensures point‑in‑time correctness for backtests.
- **pit/** – Insider disclosures (promoter/director/employee trades) and pledge creation/revocation events. Store as event logs with fields: person, transaction type, value, date, disclosure timestamp.
- **deals_hist/** – Bulk/block trades >0.5% of company with buyer/seller names. Keep as a trade‑level table for large‑trade analytics.
- **ann_full/** – 1.26M corporate announcements with category labels (results, ratings, resignations, …). Index by timestamp and ticker for event‑driven signals.
- **shareholding/** – Quarterly promoter vs public holding percentages with disclosure timestamps. Use for ownership‑change signals.
- **indices/** – Daily closes of 12+ NSE sector indices (Bank, IT, Pharma, …). Store as sector‑level benchmark series.
- **index_members/** – Thirteen point‑in‑time Nifty constituent snapshots recovered from the Internet Archive. Use for validation of synthetic membership.
- **constituents_synth.parquet** – Reconstructed monthly index membership (approx.) derived from quarterly filings and market‑cap ranking. Provides a continuous universe definition for large‑cap/mid‑cap screens.
- **reconstitution/** – NSE Indices press releases detailing add/drop announcements with effective dates. Parse PDFs or metadata to obtain exact index‑change events.
- **shareholding_detail/** – Quarterly institutional ownership broken into mutual funds, insurers, foreign investors (2.46M rows). Enables granular ownership‑concentration analysis.
- **pledge/** – Monthly promoter‑pledge snapshots (being farmed). Track pledge‑level changes over time.
- **mto/** – Legacy delivery data (2016‑19) already merged into bhav/ in the main repo’s pipeline; can be used for historical depth.

All files are flat (CSV/Parquet) and can be ingested via eqats’ existing data‑engine connectors (e.g., PyArrow, pandas) into a centralized data lake (e.g., S3 or Delta Lake). Partitioning by date/ticker will enable fast retrieval.

## Signal & Execution Logic
- **Delivery Ratio** (delivery/volume) from bhav/: a low‑turnover, high‑delivery signal suggests genuine accumulation; can be combined with price momentum for entry/exit rules.
- **Open Interest Change** from futstk/: rising OI with price increase indicates bullish futures positioning; decreasing OI on rallies warns of weakness.
- **Earnings Surprise Timing** from fr_xbrl/: using the exact public timestamp, construct post‑earnings‑announcement drift strategies that only enter after the market has digested the number.
- **Insider Trade Flow** from pit/: aggregate promoter buys vs sells, weight by transaction value, and overlay with pledge creation/revocation to gauge insider conviction.
- **Bulk/Block Deal Activity** from deals_hist/: track net buyer‑seller imbalances at the 0.5%+ threshold; persistent net buying by identified smart‑money entities can trigger long signals.
- **Announcement Sentiment** from ann_full/: use category labels (e.g., “results” positive, “resignations” negative) as a crude event score; combine with volatility filters for event‑driven trades.
- **Ownership Shifts** from shareholding/: quarterly changes in promoter % or public % signal stake‑building or divestment; sharp shifts can precede price moves.
- **Sector Relative Strength** from indices/: compute sector index returns vs Nifty50 to identify leading/lagging sectors for sector‑rotation signals.
- **Index Reconstitution Events** from reconstitution/: when a stock is announced to enter an index, anticipate forced buying by index funds; effective‑date timing allows pre‑entry positioning.
- **Synthetic Index Membership** from constituents_synth.parquet/: define dynamic large‑cap/mid‑cap universes that adjust monthly; use for universe‑filtering in factor models.
- **Pledge Levels** from pledge/: high promoter pledge ratios can be a contrarian signal (potential distress) or a risk filter; low pledge may indicate stability.
- **Combined Multi‑Factor Model**: feed the above signals into eqats’ signal engine (e.g., a linear or tree‑based model) to generate alpha scores, then route to execution modules.

## Risk Engineering
- **Liquidity Risk**: delivery vs turnover ratio from bhav/; low delivery relative to volume indicates high intraday churn and higher impact cost.
- **Futures Exposure**: open interest levels and ΔOI from futstk/ help gauge leveraged positioning; set limits on portfolio‑level futures delta.
- **Promoter Pledge Risk**: pledge/ snapshot values; flag stocks where promoter‑pledge > X% of holdings as high‑risk for forced‑sale scenarios.
- **Insider Concentration**: aggregate insider holdings from pit/ and shareholding_detail/; high insider ownership can increase idiosyncratic risk.
- **Large‑Trade Market Impact**: deals_hist/ bulk/block trade sizes; use to estimate expected slippage for large orders and adjust position‑sizing.
- **Sector Risk**: indices/ sector returns; compute sector betas and enforce sector‑neutrality or sector‑cap limits.
- **Event Risk**: ann_full/ announcements with timestamps; implement event‑windows that reduce exposure before major announcements (results, resignations).
- **Index‑Change Risk**: reconstitution/ announcements; anticipate index‑driven buying/selling pressure and adjust position limits around effective dates.
- **Ownership Concentration Risk**: shareholding/ promoter vs public % and shareholding_detail/ institutional breakdown; detect excessive ownership by a single entity or class.
- **Leverage & Margin Risk**: combine futures OI, pledge levels, and insider trading to estimate potential margin calls or forced liquidations.
- **Risk Monitoring Dashboard**: feed the above metrics into eqats’ risk engine to produce real‑time alerts, VaR contributions, and stress‑test scenarios.

## Implementation Notes
1. **Ingestion Pipeline**: Extend eqats’ data‑engine to include a new “nse_screener” source. Use scheduled jobs (e.g., Airflow) to pull updated CSVs/Parquet from the repo’s releases or direct GitHub raw URLs, then write to the eqats data lake with partitioning (date, ticker).
2. **Point‑in‑Time Fundamentals**: For fr_xbrl/, store both the announcement timestamp and the fiscal period; ensure the point‑in‑time view is respected when building factor values.
3. **Event Alignment**: Align pit/, deals_hist/, ann_full/, and reconstitution/ events to the nearest prior trading day to avoid look‑ahead bias.
4. **Feature Store**: Register the derived signals (delivery ratio, OI change, insider score, etc.) as features in eqats’ feature store for consumption by signal and risk modules.
5. **Testing**: Validate synthetic index membership constituents_synth.parquet against the 13 real snapshots in index_members/ to confirm ~90% (Nifty500) and ~84% (Nifty50) agreement before using in universe construction.
6. **Documentation**: Link to the main repo’s Chapter 3 (“the data will lie to you”) in eqats’ internal wiki to remind users of data‑quality caveats (e.g., unadjusted prices, delivery as‑published).

By integrating these datasets, eqats gains a comprehensive, timestamp‑accurate view of Indian equity markets—spanning price, fundamentals, ownership, derivatives, insider activity, and corporate events—enabling richer alpha generation and more robust risk controls.