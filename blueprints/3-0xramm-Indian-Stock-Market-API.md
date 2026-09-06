# Ingestion Blueprint: 0xramm/Indian-Stock-Market-API

## 1. Structural & Dependency Map
Summary of repository topology and inferred dependencies:

- Top-level layout
  - .gitignore
  - Readme.md (project description: "Free REST API for NSE and BSE" and "Python Flask" in description, but repository contents are JavaScript)
  - package.json (node manifest — primary executable/dependencies)
  - wrangler.toml (Cloudflare Workers configuration)
  - scripts/selfcheck.mjs (module script used for health/self-test)
  - src/
    - index.js (entrypoint / HTTP handler)
    - yahoo.js (data-fetch wrapper/adapter to Yahoo Finance)
    - format.js (response formatting, normalization)
- Languages and runtimes
  - Primary language: JavaScript (ES modules: .js/.mjs)
  - Target runtime: Node/Cloudflare Workers (wrangler.toml indicates a Workers deployment target)
- Frameworks and external systems inferred
  - Uses direct HTTP fetches to Yahoo Finance (yahoo.js)
  - Likely provides a REST API (index.js)
  - scripts/selfcheck.mjs is used for automated health checks / CI
- Dependencies
  - package.json is present — this implies some npm dependencies (not shown here), but given file count and Cloudflare target it's likely minimal (perhaps node-fetch or native fetch).
- Deployment model
  - wrangler.toml suggests the code is designed to be deployed as a Cloudflare Worker (serverless edge function).
- Notes on repo metadata mismatch
  - The repository README/description mentions Python Flask, but file contents are Node/JavaScript + Cloudflare config. For integration, assume the working implementation is JavaScript/Workers-based.

## 2. Algorithmic & Quantitative Discovery
Classify the repository functionality into the three operational domains and map files to probable responsibilities. Where nothing is present, state explicitly.

### 2.1 Data Engines
- src/yahoo.js
  - Likely implements HTTP calls to Yahoo Finance endpoints (quotes, historical, company info).
  - Expected responsibilities:
    - Build Yahoo URL(s) for symbol lookups, quote and historical data.
    - Perform fetch/GET requests and parse JSON/CSV responses.
    - Lightweight normalization of timestamps and numeric fields.
    - Potentially contains simple retry or backoff on failure.
- src/format.js
  - Likely implements normalization and formatting of Yahoo responses to a common API schema:
    - Convert Yahoo JSON to consistent fields: price, open/high/low/close, volume, symbol, company name, timestamp.
    - May convert timestamps to ISO or epoch.
    - May perform minimal aggregation or re-keying for the public API.
- src/index.js
  - HTTP layer / router that exposes endpoints for:
    - Current quote
    - Historical data / candles
    - Company/company-info lookup
  - Handles parsing incoming request parameters (symbol, start/end, interval).
- scripts/selfcheck.mjs
  - Health-check script; likely calls local endpoints to assert response shape and returns non-zero exit on errors.
- Overall data engines assessment
  - This repo implements lightweight data retrieval and formatting for market data; no long-term storage, no streaming ingestion, no local historical file ingestion.

### 2.2 Signal & Execution Logic
- None identified
  - No files imply indicator computation, signal generation, position sizing, or execution hooks.
  - index.js appears to be purely an API façade; yahoo.js/format.js focus on data retrieval and normalization only.

### 2.3 Risk Engineering
- None identified
  - No evidence of order management, risk limits, circuit breakers, position sizing, or execution slicing.
  - No throttles beyond what Cloudflare/Workers or Yahoo impose (there may be rudimentary rate limit handling, but none explicit in structure).

## 3. Steelman Critique & Adaptation Blueprint
Fit-for-purpose critique and concrete adaptation strategy for integration into the EQATS microkernel (Python/Rust/MQL5):

A. High-level objective
- The repo is a small, stateless, high-level data adapter/edge API to Yahoo Finance for Indian stock data. For EQATS, this is primarily a data-source adapter to provide market data (quotes, historical candles, company info). The microkernel expects modular, high-performance ingestion components written in Python/Rust with clear API contracts.

B. Key issues / bottlenecks to address before integration
1. Language and runtime mismatch
   - This repo is JavaScript/Cloudflare Worker–centric. EQATS core is Python with Rust components and MQL5 integration. Directly running Worker JS inside EQATS is undesirable.
2. Concurrency & performance
   - Node/Workers are single-threaded per instance; heavy parallel ingestion or bulk historical pulls will be limited by network latencies and per-worker concurrency.
   - JSON parsing and transformation in JS is decent, but large-scale ingestion (many symbols / high-frequency ticks) would benefit from native code for parsing, normalization, and caching.
3. Deployment & observability mismatch
   - Cloudflare Worker deployment model is edge-centric; EQATS may want central ingestion with persistent caches, throttling, and backfilling abilities.
4. Rate limiting & robustness
   - Implicit reliance on Yahoo Finance endpoints may hit rate limits; the repo likely lacks robust backoff, retries, deduplication, or local caching suitable for production quant ingestion.
5. Data fidelity and schema
   - The formatting layer probably maps Yahoo responses to a simplified API schema. EQATS will require strict schema contracts (types, timestamps, timezone handling) and provenance metadata.

C. Recommended adaptation and mapping into EQATS microkernel
Map each reusable piece into a microkernel module, and recommend which parts to rewrite into Rust vs Python:

1. Data Retriever (src/yahoo.js)
   - Target: Rust library (high priority)
   - Rationale: Network I/O and JSON parsing at scale; implementing the fetcher in Rust (async Tokio + reqwest or hyper) gives high throughput, fine-grained concurrency, CPU-efficient JSON parsing (serde_json) and robust error handling.
   - Expose via PyO3 to the Python microkernel as a native extension, providing functions:
     - fetch_quote(symbols: Vec<String>) -> JSON bytes / typed structs
     - fetch_historical(symbol, start_ts, end_ts, interval) -> typed OHLC vector
     - fetch_company_info(symbol) -> metadata struct
   - Features to include in Rust:
     - Connection pooling, parallel symbol fetches, configurable concurrency.
     - LRU in-memory cache with TTL (for edge-level de-duplication).
     - Rate-limit token bucket or leaky-bucket per upstream host, configurable.
     - Exponential backoff and circuit breaker for unhealthy upstreams.
     - Optional persistent cache (Redis/KV) interface for longer backfills.

2. Formatter / Normalizer (src/format.js)
   - Target: Rust for CPU-bound formatting or Python wrapper calling Rust functions (medium priority)
   - Rationale: Schema normalization and conversion (timestamp normalization, numeric coercion) can be implemented using serde for type safety and speed. Exposed to Python as a lightweight transformer returning typed Python objects or memoryviews for bulk data.
   - Provide strict schema (pydantic-compatible JSON schema exported) so EQATS modules can validate.

3. API/Adapter Layer (src/index.js)
   - Target: Python microkernel adapter (high priority)
   - Rationale: index.js provides HTTP endpoints; in EQATS the equivalent is a Source Adapter plugin in Python that:
     - Exposes the microkernel ingest API (subscribe/pull endpoints, provenance metadata).
     - Uses the Rust retriever via PyO3.
     - Implements endpoint-less deployment model (no external server unless chosen) or an optional REST shim for MQL5/other systems to call.
   - Responsibilities:
     - Parameter parsing, authentication if needed.
     - Conversion from module return values to microkernel ingestion messages and topic names.
     - Integration with EQATS scheduler for periodic pulls, on-demand fetches, and historical backfills.

4. Healthcheck & CI script (scripts/selfcheck.mjs)
   - Target: Python test harness port (low priority)
   - Rationale: Implement health checks in the EQATS test suite using pytest that call the Rust retriever/Python adapter functions and verify schema, latency, and error handling.

D. Interop and MQL5 considerations
- Expose a small REST shim or ZeroMQ bridge in EQATS that can be consumed by MQL5/EAs if needed. The preferred path:
  - Provide a Python microkernel adapter that exposes synchronous callables for the engine.
  - For MQL5, provide a thin REST endpoint or socket bridge that the EA can call, with local caching and TTL to reduce upstream traffic.

E. Example integration flow
- Microkernel ingestion task schedules: call Python adapter.get_historical("RELIANCE.NS", start, end, interval)
  - Python adapter calls Rust retriever.fetch_historical -> returns typed OHLC vector
  - Python adapter calls Rust formatter.normalize_ohlc -> validated message
  - Microkernel persists or routes data to downstream consumers (signal modules, backtest store).

## 4. Integration Verdict
Overall integration value: Medium

Rationale:
- The repository provides a useful adapter to Yahoo Finance for Indian equity data and a ready-made mapping and lightweight API. However, it lacks trading logic, risk controls, and production-grade ingestion features (caching, rate-limits, backfills). Given EQATS' architecture and goals, the code is conceptually valuable as a data-source blueprint rather than a production module to be lifted verbatim.

Top 3 concrete items to port into EQATS (in order):
1. Data fetcher logic (src/yahoo.js) — reimplement in Rust (see section 3) and expose via PyO3.
2. Response normalization/formatting (src/format.js) — port schema and normalization rules into Rust/ Python with strict typing and tests.
3. Adapter contract & routing semantics (src/index.js) — reimplement as a Python microkernel adapter plugin that orchestrates fetch/format and provides scheduling hooks.

## 5. TODO / Mitigation Task List
Priority-ordered checklist to integrate and harden this source for EQATS:

- [ ] Create a new EQATS adapter module "eqats.sources.yahoo_india" in Python that defines the microkernel plugin interface and configuration schema.
- [ ] Port yahoo.js data-fetch logic to a Rust crate:
  - [ ] Implement async fetcher using reqwest/hyper and serde for JSON.
  - [ ] Implement concurrency controls and configurable parallelism.
  - [ ] Implement upstream rate limiting (token bucket) and exponential backoff.
  - [ ] Implement in-memory LRU cache with TTL and optional Redis/KV hooks.
  - [ ] Add unit tests that mock Yahoo endpoints and validate retries and error-handling.
- [ ] Port format.js normalization logic to Rust (or Python calling Rust) and export typed structs:
  - [ ] Define canonical OHLC/time series schema and JSON schema for validation.
  - [ ] Ensure timezone handling and epoch/ISO timestamp canonicalization.
  - [ ] Validate numeric types and sentinel/NaN handling.
- [ ] Expose Rust functions to Python using PyO3 and write thin Python wrappers for microkernel consumption.
- [ ] Implement a Python-level adapter that:
  - [ ] Accepts EQATS configuration (symbols, intervals, concurrency, TTL).
  - [ ] Implements scheduled pulls, historical backfills, and on-demand queries.
  - [ ] Handles provenance metadata and data lineage (source, fetch_time, upstream_id).
- [ ] Add robust testing:
  - [ ] Unit tests for Rust retriever and formatter.
  - [ ] Integration tests in Python that exercise PyO3 bindings and end-to-end data ingestion.
  - [ ] A healthcheck harness equivalent to scripts/selfcheck.mjs (pytest).
- [ ] Implement monitoring, logging and metrics:
  - [ ] Instrument fetch latency, error rates, cache hit/miss, rate-limit events.
  - [ ] Export metrics to EQATS observability backends (Prometheus or existing EQATS stack).
- [ ] Implement deployment pattern:
  - [ ] Option A: ship Rust + Python adapter as part of EQATS services (central ingestion).
  - [ ] Option B: produce a containerized REST shim (Flask/FastAPI) wrapping the Python adapter for remote EAs—only if required for MQL5 integration.
- [ ] Add configuration-driven upstream selection and fallbacks:
  - [ ] Allow alternate sources (e.g., BSE, Yahoo backup URLs) in the adapter to provide resilience.
- [ ] Add licensing and legal check:
  - [ ] Verify Yahoo scraping/usage terms and allow users to configure acceptable upstream sources.
- [ ] Documentation:
  - [ ] Document adapter API, expected schemas, config fields, and known upstream caveats in EQATS docs.
- [ ] Security review:
  - [ ] Ensure safe parsing of untrusted upstream payloads and rate-limited public-facing endpoints.
- [ ] Deprecate / archive original JS/Worker artifacts in EQATS integration — keep as reference only.

Final note: The repository is a concise and practical reference implementation for Yahoo-based Indian market data. Its minimalism makes it straightforward to reimplement properly in Rust/Python inside EQATS. The biggest value comes from porting the actual URL patterns, parameter semantics, and formatting rules; production-grade ingestion must be implemented following the checklist above.