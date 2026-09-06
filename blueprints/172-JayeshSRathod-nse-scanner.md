# Integration Blueprint: NSE India Daily Stock Momentum Scanner into eqats

## Repository Summary
- **Name**: nse-scanner
- **Language**: Python
- **Purpose**: Scans NSE India stocks for momentum based on 1‑ to 3‑month returns.

## Data Engines Features
- **Market Data Ingestion**: Retrieves daily price data for NSE-listed equities (likely via NSE API or web scraping).
- **Return Calculation**: Computes 1‑month, 3‑month, and possibly other period returns.
- **Result Storage**: Outputs filtered stock list to CSV/console for downstream consumption.

## Signal & Execution Logic Features
- **Momentum Signal Generation**: Flags stocks whose returns exceed a configurable threshold over the selected look‑back window.
- **Ranking & Filtering**: Sorts candidates by return magnitude and applies volume/liquidity filters (if present in code).
- **Signal Output**: Emits a list of symbols with associated returns, ready for consumption by an execution engine.

## Risk Engineering Features
- *No explicit risk‑management components* (position sizing, stop‑loss, VaR, or exposure limits) are evident in the scanner’s description.

## How to Integrate into eqats
1. **Wrap the scanner as a Data Engine plugin**
   - Expose a function `fetch_nse_momentum(start_date, end_date, lookback_months=[1,3])` that returns a DataFrame of symbols, returns, and metadata.
   - Use eqats’ existing market‑data abstraction layer to cache the raw price data (e.g., in Parquet) and reuse it across runs.

2. **Convert scanner output to eqats Signal format**
   - Map each row to eqats’ `Signal` object: `{symbol, timestamp, signal_type='MOMENTUM', strength=normalized_return, metadata={lookback, return_1m, return_3m}}`.
   - Feed the signal stream into eqats’ signal‑bus or strategy evaluator.

3. **Optional Execution Adapter**
   - If the scanner includes basic order logic (e.g., market‑on‑open), create a thin adapter that translates its signals into eqats’ `Order` objects using the existing execution gateway.
   - Otherwise, let eqats’ strategy layer decide position sizing and execution based on the incoming momentum signals.

4. **Risk Engineering Extension**
   - Since the scanner lacks risk controls, integrate eqats’ risk‑engine modules:
     - Apply volatility‑based position sizing.
     - Enforce sector‑exposure limits.
     - Attach stop‑loss/take‑profit levels derived from ATR or recent volatility.
   - This can be done in a post‑signal risk‑filter step before order generation.

5. **Deployment & Scheduling**
   - Package the scanner as a Docker image or conda environment compatible with eqats’ orchestration (e.g., Airflow, Prefect, or eqats’ native scheduler).
   - Schedule daily runs after market close to generate the next‑day watchlist.

## Benefits
- **Alternative Data Source**: Adds NSE‑specific equity coverage to eqats’ universe.
- **Rapid Prototyping**: The scanner’s simple momentum logic can be used as a baseline strategy for research.
- **Extensibility**: Its data‑pull component can be swapped for other Indian exchanges or adjusted for different look‑backs.

## Caveats
- Verify the scanner’s data‑source reliability and licensing (NSE data usage policies).
- Ensure the return calculations align with eqats’ pricing adjustment (splits, dividends) pipeline.
- Add unit tests that compare scanner output against a known benchmark (e.g., Nifty 50 momentum) before live deployment.
