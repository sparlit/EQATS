# Integration Blueprint for eqats: Stock Market Circulars Repository

## Overview
The stock-market-circulars repository provides a continuously updated dataset of regulatory circulars from NSE, BSE, and SEBI, enriched with AI-generated summaries and structured metadata. This alternative data source can be leveraged by eqats for signal generation, risk monitoring, and data engine enhancements.

## Data Engines Integration
- Ingestion Pipeline: Replicate the scheduled RSS feed fetch (every 3 h) using eqats’ data engine scheduler. Pull NSE/BSE/SEBI RSS feeds, download linked PDFs, extract text via pdfminer or pymupdf.
- AI Summarization: Integrate Gemini AI (or eqats‑approved LLM) to produce concise summaries and impact tags, storing them as YAML frontmatter in markdown or as JSON records in eqats’ feature store.
- Storage Format: Adopt the markdown‑with‑YAML format for human‑readable archival, or map to eqats’ canonical schema (source, date, impact_level, affected_stocks, category, summary) in a relational or document store.
- Automation: Use eqats’ CI/CD (GitHub Actions) to trigger the pipeline, leveraging the existing just pipeline command or rewriting it as a Python module within eqats’ data_engines package.
- Environment: Reuse the Nix dev‑shell definition to guarantee reproducible builds, or containerize the pipeline with Docker for eqats’ Kubernetes jobs.

## Signal & Execution Logic Integration
- Event‑Driven Signals: Treat each new circular as an event. Generate signals based on:
  * impact_level (high/medium/low) → adjust position sizing or trigger alerts.
  * affected_stocks list → create long/short bias signals for those tickers.
  * AI‑derived category (e.g., margin‑change, listing‑rule) → map to predefined strategy templates.
- Search & Retrieval: Deploy Typesense (already integrated) as a low‑latency search service within eqats’ signal layer, enabling rapid lookup of circulars by keyword, date, or impacted symbols during strategy research.
- Execution Hooks: Expose a REST/Go endpoint (from cmd/server/) that eqats’ execution engine can poll or subscribe to via webhook to receive real‑time circular updates and trigger order adjustments.
- Backtesting: Circular markdown files provide a timestamped history; eqats can ingest them into its historical data warehouse to backtest event‑based strategies over multiple years.

## Risk Engineering Integration
- Regulatory Risk Monitoring: Use the impact_level and category fields to feed eqats’ risk engine, automatically increasing VaR or stress‑test multipliers for flagged securities when a high‑impact circular appears.
- Exposure Limits: When a circular mentions specific stocks or sectors, dynamically adjust position limits or sector caps in eqats’ risk limits service.
- Compliance Dashboard: Replicate the Hugo‑generated site (or the Go server’s HTML templates) as an internal eqats portal showing recent circulars, summary cards, and risk‑impact heatmaps.
- Alerting: Set up eqats’ alerting pipeline to push notifications (Slack, email) when a circular with impact_level: high or containing keywords like margin, circuit‑breaker, trading halt is published.
- Audit Trail: Store each circular’s raw PDF, extracted text, and AI summary in an immutable object store (e.g., S3) linked from eqats’ data lineage system for regulatory audit.

## Implementation Steps
1. Data Engine: Create a new module eqats.data_engines.circulars that mirrors the scripts/ pipeline, scheduled via eqats’ cron/Kubernetes Job.
2. Feature Store: Define a schema (source, date, impact_level, affected_stocks, category, summary, raw_text_url) and write to eqats’ feature store (e.g., Feast or PostgreSQL).
3. Signal Layer: Add a signal generator eqats.signals.circular_event that subscribes to the feature store’s change stream and emits signals based on impact and affected stocks.
4. Risk Layer: Extend eqats’ risk limits service to read the latest circulars and adjust limits via a rule engine.
5. UI/Search: Deploy Typesense index of circulars and expose a search endpoint; optionally host the Hugo site internally for qualitative review.
6. Testing & Validation: Run backtests on historical circulars (available from the repo’s hugo-site/content/circulars/) to validate signal performance and risk adjustments.

## Value Proposition
- Alternative Data: Regulatory circulars provide leading‑edge information on market rules, margin changes, and listing requirements that precede price moves.
- Automation: The existing 3‑hourly GitHub Actions workflow ensures near‑real‑time updates without manual effort.
- AI Enrichment: Gemini‑generated summaries reduce analyst workload and enable quick sentiment/impact scoring.
- Searchability: Typesense integration offers sub‑second retrieval for strategy research and risk queries.
- Governance: Structured YAML frontmatter and immutable storage satisfy audit and compliance requirements.

By integrating these components, eqats gains a robust, automated pipeline for ingesting, analyzing, and acting upon regulatory circulars, enhancing both signal generation and risk management capabilities.