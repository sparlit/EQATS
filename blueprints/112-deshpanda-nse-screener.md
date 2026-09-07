# Integration Blueprint for eqats: nse-screener Features

## Overview
The nse-screener repository provides a systematic trading research platform for Indian (NSE) and US equities, featuring robust data ingestion pipelines, a library of pre-registered strategies, and a validation harness that computes deflated Sharpe, PBO, and walk-forward consistency. These components can be mapped onto the eqats domains as follows.

## Data Engines
- **Ingestion pipelines** (`ingest/`): NSE bhavcopy (2016-present), delivery data from MTO archives, corporate actions with back-adjustment and implied-split detector, 43k quarterly results parsed from XBRL, 150k bulk/block deals, India VIX, US point-in-time S&P 500 membership, Form 4 insider purchases, 13F holdings for 15 funds, Senate trades snapshot.
- **Symbol-change master** (`ingest.renames`) maintains 1,041 canonical mappings.
- **Derived storage** under `data/` holds cleaned panels and small derived files; the full ~400 MB dataset lives in the companion `nse-screener-data` repo.
- **Automation scripts**: `backfill.py` for historical EOD, `daily.py` for end-of-day cron, and module-specific ingestors (`python -m ingest.mto`, `python -m ingest.renames`).

## Signal & Execution Logic
- **Strategy library**: pre-registered protocols (`PROTOCOL_*`) for versions v2-v5, including the standout v4 (top-20 by 12-month momentum, equal weight, monthly rebalance, 100% cash when Nifty < 200-DMA).
- **Engines**: `backtest.run` (daily engine) and `backtest.monthly` (monthly engine) execute strategies with point-in-time feature construction.
- **Paper-trial logger** (`screener/` + `paper/log.csv`) provides an append-only, machine-readable record of live out-of-sample performance.
- **Shortlist generation** (`screener/` daily shortlist, monthly portfolio) can be reused as signal generation modules.
- **Event studies** and US-market modules (`us/`) cover momentum, insider trades, 13F, Senate trades, and corporate announcements.

## Risk Engineering
- **Regime filter**: automatic 100% cash allocation when Nifty falls below its 200-day moving average (explicit risk-off rule).
- **Position sizing**: equal-weight weighting within the selected basket; monthly rebalancing controls turnover.
- **Validation harness** (`backtest.validate`) computes deflated Sharpe ratio, probability of backtest overfit (PBO), and walk-forward consistency, providing statistical risk-adjusted performance checks before capital allocation.
- **Pre-registration protocol** (`PROTOCOL_*`) ensures that strategy specifications are frozen prior to first run, eliminating post-hoc parameter rescue and reducing over-fit risk.
- **Paper-trial** (`paper/log.csv`) serves as a live-trading monitor, allowing real-time risk monitoring before any capital is committed.

## Integration Recommendations for eqats
1. **Adopt the ingestion framework**: wrap nse-screener’s `ingest/` modules as eqats data-engine plugins, exposing standardized interfaces for EOD price, corporate actions, fundamentals (XBRL), alternative data (bulk/deals, VIX, insider, 13F, Senate).
2. **Leverage the strategy template**: replicate the pre-registration (`PROTOCOL_*`) pattern in eqats to enforce protocol-first development; store each protocol as a version-controlled JSON/YAML file.
3. **Reuse the backtest engines**: eqats can call `backtest.run` and `backtest.monthly` via a thin adapter, feeding eqats-compatible feature vectors and receiving equity curves.
4. **Integrate risk controls**: embed the Nifty-200-DMA cash rule as a regime-filter module; adopt equal-weight sizing as a baseline position-sizing strategy; plug the validation harness (DSR/PBO/walk-forward) into eqats’ risk-engineering pipeline for pre-trade signal assessment.
5. **Paper-trial pipeline**: route eqats’ generated orders to a `paper/log.csv`-style append-only file, enabling transparent, timestamped out-of-sample tracking before live deployment.
6. **US-market extensions**: incorporate the `us/` subpackage (insider, 13F, Senate, VIX) into eqats’ alternative-data engine to broaden the signal universe beyond equities.

By mapping these concrete features onto eqats’ three domains, the project gains a battle-tested data pipeline, a library of rigorously validated strategies, and a robust risk-adjusted validation framework—all ready for immediate integration.