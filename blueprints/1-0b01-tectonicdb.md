# Integration Blueprint: tectonicdb -> eqats

## Summary
This blueprint describes how to integrate tectonicdb (high-performance L2 tick database) into eqats. tectonicdb is a Rust-based, compact tick store using the Dense Tick Format (DTF). It offers a small binary on-disk format, a streaming server (tdb-server), command-style client API (tdb-cli), and monitoring hooks for InfluxDB. It is intentionally a data engine: it ingests, stores, and streams ticks deterministically (timestamp+seq). It does not implement strategy or execution logic; eqats will attach signal and risk components to tectonicdb outputs.

## Goals for integration
- Use tectonicdb as the canonical tick store / low-latency replay source for eqats signal generation and backtesting.
- Stream live ticks into eqats signal pipeline using the server's SUBSCRIBE protocol.
- Use DTF files as compact archival storage and for fast deterministic replay during backtests.
- Leverage tectonicdb telemetry (PERF, COUNT, Influx integration, logs) as inputs to eqats monitoring and risk engines.

## Key facts (from repo README)
- Tick tuple format: (timestamp, seq, is_trade, is_bid, price, size).
- Stored sorted by timestamp + seq.
- Dense Tick Format (DTF): compact binary, 12 bytes per event.
- Ingest performance: ~600,000 inserts per thread/second (benchmark figure in README).
- Binaries: tdb-server, tdb-cli, dtftools (also available via cargo install).
- Command surface: HELP, PING, INFO, PERF, LOAD, USE, CREATE, GET, COUNT, CLEAR, FLUSH, SUBSCRIBE, EXISTS, ADD/INSERT.
- Configurable via environment variables: TDB_HOST, TDB_PORT, TDB_DTF_FOLDER, TDB_AUTOFLUSH, TDB_FLUSH_INTERVAL, TDB_GRANULARITY, TDB_LOG_FILE_NAME, TDB_Q_CAPACITY.
- Monitoring flags: --influx-db, --influx-host (README monitoring snippet).

## Integration components and responsibilities
1. Data Ingest (tectonicdb responsibilities)
   - Accept incoming ticks via tdb-server protocol or CLI INSERT/ADD commands.
   - Buffer in memory and periodically flush to DTF files according to TDB_AUTOFLUSH and TDB_FLUSH_INTERVAL.
   - Persist compact DTF files to disk (TDB_DTF_FOLDER).

2. Streaming / Signal feed (eqats responsibility to consume)
   - Connect eqats signal ingestors to tectonicdb via SUBSCRIBE [orderbook] for live tick streams.
   - For historical playback, use DTF files (dtftools) or tdb-server LOAD / GET commands to replay ticks in timestamp+seq order.

3. Monitoring & Risk signals (cooperative)
   - tectonicdb publishes metrics usable by eqats: PERF, COUNT, InfluxDB metrics and logs.
   - eqats risk engine should consume these metrics to detect missing data, large backlogs, or abnormal insert rates.

## Step-by-step actionable integration

Prerequisites
- Install tectonicdb binaries (recommended): download from releases or build locally:
  - cargo install tectonicdb  # installs tdb, tdb-server, dtftools
  - or build from source:
    git clone https://github.com/0b01/tectonicdb
    cd tectonicdb
    cargo build --release

Running the server
- Example server run (from README):
  ./tdb-server -vv -a -i 10000
  - -vv verbose logging, -a enable autoflush, -i 10000 sets autoflush interval (example)
- Or configure via environment variables (picked from README):
  export TDB_HOST=0.0.0.0
  export TDB_PORT=9001
  export TDB_DTF_FOLDER=db
  export TDB_AUTOFLUSH=true
  export TDB_FLUSH_INTERVAL=10000
  export TDB_Q_CAPACITY=300
  export TDB_LOG_FILE_NAME=tdb.log
  # optionally set TDB_GRANULARITY for history granularity

Ingesting ticks (examples)
- Use client commands to insert ticks directly (from README example):
  USE myorderbook
  INSERT 1505177459.685, 139010, t, f, 0.0703620, 7.65064240; INTO myorderbook
- Programmatic ingestion: write a thin adapter that sends text commands to tdb-server TCP endpoint following the CLI command protocol (ADD/INSERT). Ensure the adapter sets timestamp and seq correctly. For high-throughput, batch inserts and tune TDB_AUTOFLUSH/TDB_FLUSH_INTERVAL.

Streaming live ticks into eqats
- Live subscription: eqats should open a SUBSCRIBE socket/session to tdb-server:
  SUBSCRIBE myorderbook
  - Parse lines/messages from the server and convert to eqats internal tick record: {timestamp, seq, is_trade, is_bid, price, size}.
- Guarantee ordering: rely on tectonicdb's timestamp+seq ordering to preserve deterministic processing in eqats.

Historical replay / backtests
- Use DTF files or tdb-server LOAD/GET for historical data.
  - LOAD myorderbook  # loads from disk to memory
  - GET 100 FROM myorderbook  # fetch last 100 items
- For bulk replay: use dtftools (installed via cargo install tectonicdb) to read DTF files directly into eqats ingestion pipeline. This avoids network protocol overhead and leverages the 12-byte event layout for fast sequential reads.

Data schema mapping (explicit)
- tectonicdb tuple -> eqats tick struct:
  - timestamp (float/double) -> event_time (preserve precision)
  - seq (integer) -> seq (use for dedup/reordering safeguards)
  - is_trade (boolean) -> is_trade flag
  - is_bid (boolean) -> side (bid/ask)
  - price (decimal/float) -> price (use fixed-point/decimal in eqats if required)
  - size (decimal/float) -> size/volume

Performance & tuning
- If eqats requires near-lossless ingestion, enable TDB_AUTOFLUSH and set TDB_FLUSH_INTERVAL to a small value.
- Tune TDB_Q_CAPACITY to hold adequate history in memory for replay or short-term queries.
- For very high write rates, run multiple tdb-server instances per CPU/core and partition orderbooks across them; tectonicdb is optimized for per-orderbook insert speed (README notes per-thread throughput).

Monitoring and health checks (risk inputs)
- Enable InfluxDB reporting when launching tdb-server (flags from README). Configure eqats monitoring to ingest those metrics.
- Use PERF and COUNT endpoints to detect abnormal conditions:
  - PERF returns answercount over time; a sudden drop can mean missing data or ingestion failure.
  - COUNT / COUNT ALL to detect gaps vs expected volumes.
- Implement alert rules in eqats risk/ops based on:
  - sustained missing ticks for subscribed orderbooks
  - large growth in queue/backlog (TDB_Q_CAPACITY saturation)
  - unusual insert rate spikes (compare against expected baseline; README gives a perf benchmark to set thresholds)

Risk control integration pattern (recommended)
- Implement a Watcher component in eqats that subscribes to tectonicdb telemetry and the live SUBSCRIBE feed.
  - For every tick, compute derived metrics (microstructure, arrival rate, spread changes) and forward to Risk Engine.
  - Use COUNT/PERF periodically to validate data completeness and cross-check against internal counters.
- Enforce action on risk alerts: pause automated executions, switch to safe-mode data source, or trigger manual review.

Operational runbook snippets
- Start server with autosave every 10k inserts:
  TDB_AUTOFLUSH=true TDB_FLUSH_INTERVAL=10000 ./tdb-server -a
- Subscribe from eqats (pseudo):
  connect_tcp(TDB_HOST,TDB_PORT)
  send_text('SUBSCRIBE myorderbook')
  loop read -> parse tick -> emit to signal pipeline

Limitations / gaps (explicit)
- tectonicdb is a data engine: it does not implement strategy logic, order execution/routing, or position limits. Those must be implemented inside eqats.
- Risk-engineering features (position limits, pre-trade checks) are not present; use tectonicdb telemetry and eqats' own risk modules to enforce.
- The README references "Google Cloud Storage and Data Collection Backend integration" configuration via environment variables but does not enumerate the full cloud push mechanism; for durable remote archival you should rely on the DTF files in TDB_DTF_FOLDER and implement a separate uploader (e.g., GCS client) or inspect the repo docs for cloud upload tooling.

Deliverables for a first integration sprint (concrete tasks)
1. Provision tectonicdb test instance and validate basic commands (CREATE, USE, INSERT, GET, SUBSCRIBE).
2. Build an eqats adapter that can:
   - Programmatically INSERT ticks into tectonicdb (ingest test data).
   - Subscribe to live updates via SUBSCRIBE and inject into eqats signal pipeline.
   - Read historical DTF files using dtftools for backtests.
3. Add a Watcher in eqats to poll COUNT/PERF and ingest InfluxDB metrics; implement 3 basic alerts: missing-data, backlog growth, erratic insert rate.
4. Document runbook for starting tectonicdb with env var examples and performance tuning notes.

Appendix: Useful README-derived commands & examples
- Run server example:
  ./tdb-server -vv -a -i 10000
- Insert example (from README):
  INSERT 1505177459.685, 139010, t, f, 0.0703620, 7.65064240; INTO dbname
- Environment variables (configure server behavior):
  TDB_HOST, TDB_PORT, TDB_DTF_FOLDER, TDB_AUTOFLUSH, TDB_FLUSH_INTERVAL, TDB_GRANULARITY, TDB_LOG_FILE_NAME, TDB_Q_CAPACITY
- Monitoring flags (from README snippet):
  --influx-db <influx_db> --influx-host <influx_host>

This blueprint uses only features and configuration options explicitly present in the tectonicdb README. It avoids assuming unlisted capabilities (e.g., built-in cloud upload endpoints or execution logic). The recommended integration places tectonicdb as eqats' authoritative tick engine and prescribes concrete adapters for live subscription, DTF-based replay, monitoring ingestion, and risk-alert wiring.