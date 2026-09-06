# Integration Blueprint for eqats

## Overview
The NSE 52‑Week Pullback Screener is a Streamlit app that identifies Indian equities that made a 52‑week high >3 months ago and are now 1‑10 % below that peak, with optional filters for F&O, volume, and listing age. Its core logic can be reused as a signal generator inside the eqats quantitative trading framework.

## Data Engines Integration
1. **Market‑data ingestion** – Replace the ad‑hoc yfinance calls with eqats’ unified data engine (e.g., a feature‑store or daily bar downloader). Pull OHLCV for the NSE equity universe and compute trailing 52‑week highs.
2. **Static reference data** – Keep the bundled `data/nse_equity_list.csv` as a seed list; eqats can maintain this list in its instrument‑metadata table and refresh it via the existing `update_fo_list.py` script (or a similar job) to keep the F&O flag current.
3. **Price‑band feed** – If eqats needs exchange‑defined circuit limits, adopt the Angel One SmartAPI workflow (`.github/workflows/update-bands.yml`) as a scheduled GitHub Action that writes a `price_bands.csv` artifact. eqats can ingest this file as a reference table for volatility‑based filters.
4. **Storage** – All CSV artifacts can be stored in eqats’ data lake (e.g., S3 or Azure Blob) under a `screeners/nse_52wk/` prefix, enabling versioning and back‑testing.

## Signal & Execution Logic Integration
1. **Signal module** – Encapsulate the screener logic in a Python function `generate_nse_52wk_pullback_signals(df, params)` where `df` contains daily OHLCV and metadata (listing date, F&O flag, band). The function returns a DataFrame with columns matching the app’s output (`LastClose`, `52wHigh`, `HighDate`, `DaysSinceHigh`, `PctFromHigh`, `AvgVol20d`, `F&O`, `Band%`, `ListingDate`, `Basis`) and a boolean `signal` flag.
2. **Parameterisation** – Make the three optional filters configurable via eqats’ strategy‑parameter interface (e.g., YAML or JSON). Defaults: `days_since_high > 90`, `pct_from_high between 1 and 10`, `fo_only=False`, `volume_filter=None`, `listing_window_months=(3,12)`.
3. **Execution hook** – The signal DataFrame can be fed into eqats’ order‑generation pipeline (e.g., weight‑by‑inverse‑volatility or equal‑weight) and passed to the execution adapter (IB, Zerodha, etc.). Because the screener is end‑of‑day, signals can be executed at the next session’s open.
4. **Back‑testing** – Reuse the same function in eqats’ back‑tester by feeding historical bars; the optional filters can be toggled to study their impact on turnover and hit‑rate.

## Risk Engineering Integration
- The repository does not contain explicit risk‑limits or position‑sizing logic. When integrating into eqats, apply the existing risk‑engine (max‑position‑size, sector‑caps, stop‑loss, volatility‑scaling) to the signals produced.
- The shared‑passcode protection can be mirrored by eqats’ authentication layer (e.g., OAuth or API‑key gating) if the screener is exposed as an internal service.
- Volume‑based filters already act as a liquidity guard; eqats can treat them as pre‑trade liquidity checks within its risk module.

## Deployment & Ops
- Containerise the signal module (Docker) and schedule it via eqats’ workflow orchestrator (Airflow, Prefect, or GitHub Actions) to run after market close.
- Store the output CSV in eqats’ signal catalogue; optionally push a lightweight Streamlit dashboard (reusing `app.py`) for internal monitoring, secured via eqats’ SSO.
- Keep the Angel One SmartAPI credentials as eqats‑managed secrets (e.g., in a vault) and reuse the existing update‑bands workflow or replace it with eqats’ native secret‑rotation mechanism.

## Benefits
- Provides a ready‑made, low‑turnover equity‑pullback signal for the Indian market.
- Leverages existing data‑pipeline components (yfinance, CSV reference data, scheduled API jobs) with minimal adaptation.
- Offers a transparent, rule‑based signal that can be combined with other eqats strategies or used as a filter in a broader portfolio construction process.