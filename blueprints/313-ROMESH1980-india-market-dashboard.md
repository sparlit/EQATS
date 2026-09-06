# Integration Blueprint: India Market Intelligence Dashboard into eqats

## Overview
The india-market-dashboard repository provides a zero‑cost, static research dashboard for NSE & BSE securities. Its core value lies in the automated ingestion and curation of exchange‑master data via GitHub Actions, plus a roadmap for EOD price/volume import and fundamental signal generation.

## Data Engines Integration
- Master Data Ingestion: Reuse the existing GitHub Action workflow (update-data.yml) to pull the official NSE Equity + SME master (and optionally BSE) on a daily basis. The workflow already preserves older rows on failure, a pattern that can be adopted in eqats’ data‑engine layer for robust master‑file updates.
- ISIN‑based Merging: Implement the ISIN merge logic as a reusable Python utility (pandas‑based) to unify NSE and BSE instrument lists, creating a canonical instrument universe for eqats.
- Static Storage Pattern: The dashboard stores the master data as JSON/CSV files served via GitHub Pages. In eqats, we can adopt a similar approach for distributing reference data (e.g., instrument metadata) to downstream services or for back‑testing environments.
- Future EOD Bhavcopy Importer: When the project adds the Bhavcopy importer for price, volume, and turnover, eqats can plug this into its historical market‑data pipeline, enabling end‑of‑day bar construction for Indian equities.

## Signal & Execution Logic Integration
- Signal Placeholders: The UI currently displays six signal categories (Sector Strength, Macro Support, Value Migration, Future Growth, Fundamental Quality, CAPEX, Overall Score) as blank placeholders. eqats can adopt this signal‑catalog structure and fill it with its own model outputs.
- Relative‑Strength & Sector‑Strength: Planned calculations based on EOD history map directly to eqats’ factor‑engine; implement as rolling‑rank or z‑score pipelines.
- Filing Parser: The announced parser for quarterly results and CAPEX disclosures can feed fundamental‑quality and CAPEX signals into eqats’ fundamental‑model module.
- Announcement Keyword Classifier: A lightweight NLP classifier for press releases can generate event‑driven signals (capacity expansion, order book, policy tailwinds) suitable for eqats’ execution‑logic layer.

## Risk Engineering Integration
- No explicit risk‑management features are present in the source repository. eqats can therefore contribute risk‑limits, position‑sizing, and real‑time monitoring modules that consume the dashboard’s data and signals.

## Implementation Steps
1. Fork the india-market-dashboard repo and adapt the GitHub Action to push data to eqats’ internal artifact store (e.g., S3 or GCS).
2. Extract the ISIN‑merge utility into a shared Python package used by both the dashboard and eqats’ data‑engine.
3. Design a signal‑catalog schema matching the UI’s six categories; map eqats’ model outputs to these fields.
4. Implement the planned EOD Bhavcopy importer, filing parser, and announcement classifier as eqats plugins, then feed their outputs into the signal catalog.
5. Add risk‑engine components (VaR limits, exposure checks, stop‑loss monitors) that subscribe to the signal catalog and instrument master.

## Benefits
- Leverages a proven, zero‑cost data‑collection workflow for Indian exchange master data.
- Provides a ready‑to‑extend UI for visualizing eqats‑generated signals and fundamentals.
- Enables rapid prototyping of Indian‑market strategies using authentic, exchange‑sourced reference data.

## Caveats
- The dashboard is EOD only; real‑time execution would require additional market‑data feeds.
- Signal values are currently placeholders; validation against reliable fundamentals is needed before live deployment.
- GitHub Actions are subject to public‑repo usage limits; high‑frequency data pulls may need migration to a dedicated CI/CD system.
