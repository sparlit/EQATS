# Integration Blueprint: ai-stock-screener → eqats

## Overview
The ai-stock-screener repository provides a full‑stack pipeline for screening NSE equities using technical indicators (EMA/RSI) and AI‑driven scoring via Google Gemini. Its components can be mapped to eqats domains and reused as plug‑in modules.

## Data Engines
- **Market Data Ingestion**: Uses `yfinance` to pull 3‑month daily price data for NSE tickers. eqats can replace or augment its own data feed with this connector, especially for Indian equities.
- **Technical Indicator Engine**: `data_screener.py` computes 20‑day and 50‑day EMA and 14‑day RSI. These calculations can be extracted as a reusable indicator library for eqats’ data engine.
- **Stock Universe Management**: `stock_universes.py` maintains categorized ticker lists (Nifty 50, Largecap, etc.). eqats can import these universes to define its coverage universe.
- **Storage**: Neon PostgreSQL stores user credentials and session data via Flask‑JWT‑Extended. eqats could adopt the same JWT‑based auth pattern or reuse the schema for user‑specific settings.

## Signal & Execution Logic
- **Technical Filter**: Screens for `Price > 20‑EMA > 50‑EMA` and `RSI ∈ [40,80]`. This rule set can be directly incorporated into eqats’ signal generation layer as a pre‑filter.
- **AI Scoring Pipeline**: `pipeline.py` combined with LangGraph passes filtered stocks to Google Gemini (`gemini-3.6-flash`) which returns a JSON object containing:
  - `confidence_score` (0‑100)
  - `conviction` (High/Medium/Low)
  - `investment_thesis`
  eqats can call the same Gemini endpoint (or wrap the LangGraph workflow) to produce an AI‑augmented confidence signal.
- **Signal Aggregation**: Stocks scoring ≥ 50 are sorted and returned to the frontend. eqats can adopt this threshold or make it configurable, feeding the sorted list into its execution engine.
- **Optional Logging**: The pipeline can write raw Gemini responses to `gemini_analysis.txt`; eqats could enable similar audit logging for compliance.

## Risk Engineering
- **No explicit risk‑management features** are present in the repository (no position sizing, stop‑loss, risk limits, or monitoring). Integration would therefore require eqats to supply its own risk controls (e.g., volatility‑based sizing, max drawdown limits) around the signals received from the screener.

## Integration Steps
1. **Data Layer** – Add a `yfinance`‑based ingestor for NSE symbols, reuse the EMA/RSI functions, and load the stock universes from `stock_universes.py`.
2. **Signal Layer** – Plug the technical filter as a pre‑screen; invoke the Gemini/LangGraph pipeline (or a microservice wrapper) to obtain AI scores; apply the ≥ 50 threshold and sort.
3. **Execution Layer** – Feed the ranked list into eqats’ order‑management system, applying eqats’ risk‑engineering rules (position sizing, stop‑loss, exposure limits) before order submission.
4. **Operational** – Deploy the backend on a cloud‑run service (or keep on PythonAnywhere) and expose the scoring endpoint; secure it with JWT using the same `JWT_SECRET_KEY` pattern; store user preferences in the Neon Postgres schema.
5. **Monitoring** – Enable the optional Gemini log file or forward logs to eqats’ monitoring pipeline for audit trails.

## Benefits
- Rapid access to Indian‑market data and pre‑built indicator calculations.
- State‑of‑the‑art LLM‑based thesis generation that can enrich eqats’ signal explainability.
- Ready‑made authentication and user‑management infrastructure.

## Considerations
- Verify licensing of `yfinance` and Gemini usage for commercial eqats deployment.
- Ensure data latency aligns with eqats’ trading frequency (the screener uses end‑of‑day data; for intraday strategies a higher‑frequency feed would be needed).
- Since risk controls are absent, eqats must overlay its own risk engine to satisfy regulatory and capital‑allocation requirements.