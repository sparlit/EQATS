# Integration Blueprint for eqats

## Overview
The `longbridge-terminal` repository provides a Rust‑based, AI‑native CLI for the Longbridge trading platform. It offers comprehensive market data access, portfolio information, and order management through the Longbridge OpenAPI, all accessible via simple terminal commands with JSON output for machine consumption. This blueprint outlines how the most valuable features can be incorporated into the eqats quantitative trading system to enhance its data ingestion, strategy execution, and (where applicable) risk monitoring capabilities.

## Data Engines Integration

### Market Data Ingestion
- **Real‑time Quotes & Depth**: Use `longbridge quote <symbols>` and `longbridge depth <symbol>` to stream live prices and Level 2 order‑book data directly into eqats’ market‑data engine. The JSON output (`--format json`) can be parsed by eqats’ data normalizers.
- **Trade & Intraday Feeds**: `longbridge trades <symbol> [--count N]` provides recent tick‑by‑tick trades; `longbridge intraday <symbol>` supplies minute‑by‑tick price/volume for the current session. These feeds can populate eqats’ high‑frequency storage layer.
- **Historical OHLCV**: `longbridge kline history <symbol> --start YYYY-MM-DD --end YYYY-MM-DD` (or the non‑history variant for latest bars) delivers adjustable OHLCV candles, enabling eqats to back‑test and update its historical price database.
- **Static & Fundamental Data**: `longbridge static <symbol>` returns reference information (lot size, currency, etc.); `longbridge calc-index <symbol> --fields pe,pb,eps` supplies valuation ratios; `longbridge capital <symbol>` gives capital‑flow snapshots. These can enrich eqats’ fundamental dataset for factor construction.
- **Market Sentiment & Index Constituents**: `longbridge market-temp [HK|US|CN|SG]` yields a bullish/bearish temperature index; `longbridge constituent <index> [--sort market-cap]` returns index members. Such macro‑sentiment and constituent lists can be fed into eqats’ regime‑detection and universe‑selection modules.
- **Portfolio Data**: Although not shown in the snippet, the description notes that the CLI covers account balances and stock/fund positions. Commands like `longbridge positions` (inferred) would provide eqats with real‑time portfolio snapshots for risk‑adjusted performance tracking.

### Storage & Normalization
All CLI commands support `--format json`, making it straightforward to pipe output into eqats’ ingestion pipelines (e.g., via `jq` or direct HTTP hooks). The data can be normalized into eqats’ canonical schema (symbol, timestamp, bid/ask, volume, etc.) and stored in the preferred time‑series database (e.g., InfluxDB, TimescaleDB) or object store for later retrieval.

## Signal & Execution Logic Integration

### Signal Generation
- eqats can invoke the CLI as a subprocess or via a Rust wrapper that calls the Longbridge SDK directly, retrieving real‑time quotes, depth, or capital‑flow data to compute signals (e.g., order‑book imbalance, VWAP deviation, PE‑based value signals).
- The `--count` / `--limit` alias facilitates AI‑agent friendly pagination, allowing eqats’ reinforcement‑learning or LLM‑based agents to request a fixed number of recent trades or depth levels.
- Shell completion and scripting support enable rapid prototyping of signal‑generation scripts directly in the terminal, which can later be migrated into eqats’ strategy repository.

### Order Execution
- The CLI already implements order submission, modification, cancellation, and execution history (per the README’s “trading” coverage). eqats can leverage these commands to send orders:
  - `longbridge order submit --symbol SYMBOL --side BUY --qty QTY --price PRICE --type LIMIT`
  - `longbridge order cancel --order-id ID`
  - `longbridge order amend --order-id ID --qty NEW_QTY --price NEW_PRICE`
  - `longbridge order history [--count N]` for audit trails.
- Because the CLI handles OAuth 2.0 token management via the Longbridge SDK, eqats does not need to manage tokens separately; a single `longbridge auth login` session suffices for both data and trading endpoints.
- The JSON output mode allows eqats to parse order responses (status, filled quantity, average price) and update its execution‑state machine in real time.

### AI‑Agent Compatibility
- The tool’s design for “AI‑agent tool‑calling” means eqats’ LLM‑driven agents can treat each CLI command as a tool, invoking them with structured arguments and receiving JSON results, simplifying integration with frameworks like LangChain or custom agent loops.

## Risk Engineering Integration

The README does not describe explicit risk‑limit, position‑sizing, or real‑time risk‑monitoring features (e.g., VaR, leverage limits, stop‑loss automation). Consequently, there are no direct risk‑engineering components to import. However, eqats can still use the available market‑data and capital‑flow feeds to compute its own risk metrics (e.g., intraday drawdown, concentration, leverage) and enforce limits internally.

## Implementation Steps

1. **Authentication Setup**
   - Run `longbridge auth login` once to obtain and cache the OAuth token (shared between CLI and any Rust SDK wrapper).
   - Verify with `longbridge check`.

2. **Data Ingestion Layer**
   - Create a thin Rust wrapper (or use `tokio::process::Command`) around the `longbridge` binary for each market‑data endpoint needed.
   - Parse JSON output into eqats’ market‑data structs.
   - Schedule periodic calls (e.g., websocket‑style polling via repeated `quote` or `depth` calls) or use the provided streaming endpoints if available.
   - Store raw JSON or normalized records in eqats’ data lake.

3. **Signal Engine Hooks**
   - Implement strategy functions that request data via the wrapper (e.g., get latest order‑book depth, compute imbalance).
   - Use `--format json` and `--limit` to control payload size for low‑latency loops.
   - Log signals to eqats’ signal bus for execution.

4. **Execution Adapter**
   - Wrap order‑related CLI calls (`order submit`, `cancel`, `amend`, `history`) in an execution adapter that translates eqats’ order objects to CLI arguments and maps CLI responses back to order status updates.
   - Ensure idempotency and handle error codes (e.g., insufficient margin, rejected).

5. **Testing & Validation**
   - Use the CLI’s built‑in `longbridge check` to validate connectivity before live runs.
   - Paper‑trade using Longbridge’s sandbox (if available) by pointing the CLI to the test environment via environment variables or flags.
   - Compare execution reports from the CLI with eqats’ internal order‑management system.

6. **Observability**
   - Leverage `longbridge market-temp` and `capital --flow` as supplementary inputs to eqats’ risk dashboard.
   - Monitor CLI latency and error rates; adjust polling intervals accordingly.

## Conclusion
By integrating the `longbridge-terminal` CLI (or its underlying Longbridge SDK) into eqats, the system gains:
- Reliable, real‑time and historical market data across multiple asset classes.
- Programmatic access to portfolio and order‑management capabilities.
- A straightforward, JSON‑friendly interface suitable for both traditional quant strategies and AI‑agent driven workflows.
While risk‑specific features are absent, the rich data streams enable eqats to build its own risk‑monitoring layer on top of the provided market and capital‑flow information.

This blueprint provides a concrete, actionable path to harness the strengths of the Longbridge Terminal within the eqats quantitative trading platform.