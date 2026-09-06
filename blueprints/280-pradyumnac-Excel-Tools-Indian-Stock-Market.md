# Integration Blueprint for Excel Tools for Indian Stock Markets

## Repository Overview
- Name: Excel-Tools-Indian-Stock-Market
- Primary Language: Batchfile (with VBA macros inside Excel workbooks)
- Key Functionality: Downloads the latest NSE Bhavcopy, calculates intraday metrics, filters liquid stocks, and ranks them by low delivery percentage to highlight heavily traded stocks.

## Data Engines Integration
- Market Data Ingestion: Replace the manual Bhavcopy download with eqats's data engine that pulls NSE end-of-day CSV via the NSE API or a CSV feed.
- Feature Computation: Replicate the calculated fields (Day Change, Day Change %, True Range, True Range %, Close-vs-VWAP) as derived columns in eqats's feature store.
- Filtering Pipeline: Apply the same filters (volume >= 100k, True Range % > 1, Close > INR 25) as a preprocessing step before signal generation.
- Sorting & Output: Sort by Delivery % ascending and expose the top-N list as a lookup table for downstream modules.

## Signal & Execution Logic Integration
- Signal Generation: Treat the ranked list as an alpha signal: stocks appearing in the top quartile receive a long-bias intraday signal; those with extremely low delivery may be flagged for short-selling or avoidance.
- Execution Hook: In eqats, the signal can be consumed by the Signal & Execution Logic layer to generate orders (e.g., market-on-open or VWAP-aligned entries) with appropriate position sizing.
- Signal Refresh: Since the tool works on end-of-day data, the signal can be refreshed daily before market open and fed into the execution engine for the next trading session.

## Risk Engineering Integration
- Risk Controls: The repository does not embed explicit risk limits; therefore, eqats's existing risk engine should overlay its standard controls:
  * Max position size per stock (e.g., 1% of equity).
  * Volatility-based stop-loss using the computed True Range.
  * Daily loss limits and exposure caps.
- Monitoring: Log the signal’s delivery-percentage metric as a risk attribute to monitor for regime changes (e.g., sudden rise in delivery indicating reduced speculative interest).

## Implementation Steps
1. Data Adapter – Write a thin adapter that pulls NSE Bhavcopy and maps columns to eqats's canonical schema.
2. Feature Module – Add a feature-calculation step that reproduces the five metrics and the delivery-percentage filter.
3. Signal Node – Create a signal node that ranks stocks by delivery % and outputs a signal score (e.g., inverse of delivery %).
4. Risk Overlay – Ensure the risk engine applies position-sizing rules and stop-loss based on the true-range column.
5. Testing – Back-test the signal using eqats's historical data pipeline to verify performance before live deployment.

## Expected Benefits
- Provides a ready-made, liquidity-filtered universe of Indian equities suited for short-term strategies.
- Leverages a simple, transparent metric (low delivery %) that captures short-term trader interest.
- Easy to maintain because the core logic resides in eqats's Python/Julia stack rather than embedded Excel macros.

## Caveats
- The original tool relies on end-of-day data; intraday timing must be handled separately.
- Ensure data licensing compliance when redistributing NSE Bhavcopy files.
- The signal may be crowded; combine with additional filters (e.g., volatility, sector neutrality) for robustness.
