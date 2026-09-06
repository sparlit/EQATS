# Integration Blueprint for Nifty-500 Live Sentiment Analysis into EQATS

## Overview
Integrate real-time sentiment scores derived from FinBERT model applied to news/articles as a signal engine within EQATS.

## Components
- **Data Engine**: Acquire news via Google Finance, Yahoo Finance, (optional) Google News, StockTwits; store raw articles in DuckDB.
- **Signal & Execution Logic**: PyO3 Rust module eqats_sentiment exposes get_sentiment(text) -> f32 using HuggingFace finbert-tone via Python's transformers library.
- **Risk Engineering**: Sentiment scores feed into risk models to adjust position sizing, volatility estimates, and generate sentiment‑based risk alerts.

## Data Flow
1. External news fetcher (Python) writes raw text to DuckDB table raw_news.
2. A scheduled job reads new rows, calls eqats_sentiment::get_sentiment via PyO3, stores sentiment score in table sentiment_signals.
3. EQATS strategy layer queries sentiment_signals to generate long/short signals.
4. Risk engine consumes sentiment‑adjusted volatility to compute position limits.

## API
rust
// Python side (exposed via PyO3)
fn get_sentiment(text: &str) -> f32

Returns a value in [-1, 1] where >0 indicates bullish sentiment.

## Testing
Unit test validates output range; integration test can be run with cargo test --features python requiring transformers and torch installed.

## Deployment
Build the PyO3 extension as part of EQATS Python package; ensure transformers>=4.30, torch>=2.0 are available in the runtime environment.