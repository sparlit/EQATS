# Integration Blueprint for stock-market-india into eqats

## Overview
The stock-market-india npm package provides a simple HTTP API that exposes a wide range of NSE and BSE market data endpoints. It can be used as a lightweight data‑engine for eqats to obtain real‑time and historical Indian equity information without building custom scrapers.

## Data Engines Integration
- **Market status** – poll `GET /get_market_status` to determine whether the market is open or closed and gate eqats’ trading loops.
- **Indices & quotes** – use `GET /nse/get_indices`, `GET /nse/get_quote_info`, and `GET /nse/get_multiple_quote_info` to populate eqats’ canonical ticker table with last price, change, high/low, etc.
- **Gainers/losers** – `GET /nse/get_gainers` and `GET /nse/get_losers` provide ready‑made momentum signals.
- **Advances/declines** – `GET /nse/get_incline_decline` gives breadth data useful for market‑wide risk gauges.
- **Index constituents** – `GET /nse/get_index_stocks?symbol=nifty` and search endpoint enable building watch‑lists and sector‑based filters.
- **Intraday data** – `GET /nse/get_intra_day_data?companyName=TCS&time=1` (or `month`) returns XML that can be parsed into tick‑level bars for high‑frequency strategies.
- **Historical chart data** – `GET /nse/get_chart_data_new` returns pipe‑delimited CSV (date|open|high|low|close|volume) suitable for loading into eqats’ time‑series store (e.g., TimescaleDB) for back‑testing and indicator calculation.
- **52‑week extremes** – `GET /nse/get_52_week_high` and `GET /nse/get_52_week_low` help identify breakout or breakdown candidates.
- **Liquidity & volume** – `GET /nse/get_top_value_stocks` and `GET /nse/get_top_volume_stocks` provide rankings for slippage‑aware execution.
- **Futures data** – `GET /nse/get_stock_futures_data` supplies term‑structure information for futures‑based spreads and basis‑trading signals.
- All responses are JSON (except intraday XML and chart CSV) and can be normalized into eqats’ internal market‑data schema via a thin adapter.

## Signal & Execution Logic
The repository does **not** contain any signal generation or order‑execution logic. eqats would need to implement its own strategies using the data fetched from these endpoints. Examples:
- Compute a daily momentum score from the gainers/losers lists.
- Derive intraday VWAP or volume‑weighted moving averages from the intraday XML feed.
- Use index constituent changes to rebalance sector‑neutral portfolios.
- Build basis‑trading signals from spot‑future price differences obtained via the futures endpoint.

## Risk Engineering
No built‑in risk limits, position‑sizing, or monitoring features are present. eqats would apply its own risk engine on the ingested data, for example:
- Enforce max‑position limits based on liquidity rankings from top‑volume stocks.
- Use 52‑week high/low to set dynamic stop‑loss levels.
- Monitor advances/declines for market‑wide stress indicators.
- Apply volatility‑adjusted position sizing using historical price series from the chart data endpoint.

## Implementation Steps
1. **Adapter** – Create an `eqats-adapter-nse` module that wraps the HTTP calls, handles authentication (if ever required), and normalizes each endpoint’s payload into eqats’ canonical market‑data objects.
2. **Ingestion scheduler** – Integrate the adapter with eqats’ data‑ingestion framework (cron‑based jobs or event‑driven workers) to pull market status every minute, quotes every second during market hours, intraday ticks at the desired granularity, and end‑of‑day historical CSVs after close.
3. **Storage** – Write normalized JSON to eqats’ preferred store (e.g., PostgreSQL/TimescaleDB for time‑series, Redis for latest snapshots, S3 for raw CSV/XML).
4. **Signal pipeline** – Feed the real‑time quotes and derived indicators into eqats’ signal‑generation services.
5. **Risk monitoring** – Route the same data stream to eqats’ risk‑service for real‑time limit checks and margin calculations.
6. **Testing & validation** – Use the package’s sample responses to unit‑test the adapter; run paper‑trading simulations to validate signal logic before going live.

## Considerations
- **Rate limits** – Although the endpoints are currently open, implement exponential back‑off and cache responses where appropriate (e.g., market status changes infrequently).
- **Data format conversion** – Parse XML intraday responses into JSON; split pipe‑delimited CSV into columns and cast types.
- **Error handling** – Detect missing fields, fallback to previous close, and raise alerts for prolonged outages.
- **Security** – If the API ever requires keys, store them in eqats’ secret manager and inject them at runtime.
- **Legal** – Review NSE/BSE terms of service to ensure compliance when redistributing or storing the data.

## Expected Benefits
- Immediate access to a comprehensive suite of Indian equity market data without building and maintaining scrapers.
- Reduces time‑to‑market for India‑focused strategies (e.g., NIFTY‑based arbitrage, sector rotation, futures‑basis trading).
- Provides a reliable, versioned data source that can be swapped or complemented with other feeds as eqats scales.
