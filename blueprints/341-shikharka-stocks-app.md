# Integration Blueprint: Stocks App Quote Fetch into eqats

## Overview
Integrate the quote‑fetching capability of shikharka/stocks-app into the eqats quantitative trading platform. The Node.js app scrapes Yahoo Finance for NSE/BSE quotes and stores historical data in MongoDB. In eqats we expose the same functionality as a Rust library (PyO3 optional) that can be called from the data engine, signal/execution logic, and risk engineering modules.

## Data Engine Integration
- **Real‑time quote acquisition**: Use reqwest to GET the Yahoo Finance quote page and scraper to extract fields (close, prevClose, open, volume, avgVolume3Months, marketCap, monthly5Years, peRatio, epsRatio).
- **Historical persistence**: Provide a function to write a batch of quotes for a given exchange into a MongoDB collection (mirroring the /writeQuotes endpoint). This populates the eqats historical store for later analysis.
- **Configuration**: Port, MongoDB URL, database name, max retries, timeout are exposed via a config struct similar to the original config.json.

## Signal & Execution Logic Integration
- The real‑time quote struct can be fed directly into eqats’ signal generation pipeline (e.g., moving‑average cross, RSI, breakout detectors).
- A thin wrapper exposes a get_quote(exchange, symbol) async function that returns a Quote struct; the execution engine can subscribe to a stream of quotes and issue orders when user‑defined conditions are met.

## Risk Engineering Integration
- Historical close/volume series stored by the data engine enable calculation of volatility, value‑at‑risk, drawdown, and correlation matrices.
- The integration provides a helper to read the MongoDB collections and return time‑series vectors for risk‑model consumption.

## Implementation Details
- **Language**: Rust 2021 edition.
- **Dependencies**: reqwest = { version = "0.11", features = ["json"] }, scraper = "0.15", mongodb = "2.5".
- **Error handling**: All I/O operations return Result<T, Box<dyn std::error::Error>>; retries follow the maxTry setting.
- **Testing**: Unit tests mock HTTP responses with wiremock or use vcr‑style fixtures; integration test spins up a temporary MongoDB instance via mongodb-test crate.

## Testing
- cargo test runs:
  - test_get_quote_success: verifies parsing of a sample Yahoo Finance HTML snippet.
  - test_write_quotes: inserts a dummy batch into an in‑memory MongoDB and checks collection counts.
- CI pipeline runs on Linux/macOS/windows.

## Future Work
- Add PyO3 bindings to expose get_quote and write_quotes to Python strategies.
- Replace scraping with Yahoo Finance unofficial API if reliability improves.
- Add WebSocket streaming for real‑time push.