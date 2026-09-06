# Integration Blueprint for bhavcopy into eqats

## Overview
bhavcopy downloads BSE/NSE bhavcopy CSVs and stores them in a SQLite database with an equity table containing OHLCV data. This provides a ready‑made historical market data store for eqats.

## Data Engine Integration
- Run bhav as a scheduled job: `bhav --filename eqats.db --from <last_date> --until <today>` to incrementally fetch new sessions.
- Optionally use `--save-patch` to keep changesets for audit.
- The resulting SQLite file can be mounted read‑only; eqats accesses it via standard `database/sql` drivers.
- The table’s composite primary key (exchange, trading_date, ticker, type) guarantees unique records, eliminating extra dedup steps.

## Signal & Execution Logic
- Strategies import a thin Go wrapper that exposes `GetOHLCV(exchange, ticker, date)` and `ListTickers(exchange, date)`.
- Historical series are used for indicator calculations; live strategies can reference the latest close prices stored in the DB.
- No direct signal generation is performed by bhavcopy; it serves purely as a data source.

## Risk Engineering
- Clean OHLCV series enable accurate volatility, VaR, and exposure calculations in eqats’ risk engine.
- Patch files produced by `--save-patch` can be archived to meet regulatory traceability requirements.

## Benefits
- Single portable SQLite file containing both BSE and NSE data.
- Incremental sync reduces bandwidth and avoids exchange IP bans.
- Schema matches typical OHLCV needs; no migration work.
- Auditability via patch files.

## Implementation Steps
1. Add bhavcopy binary or source as a dependency.
2. Create a Go module `data/engine/bhavcopy.go` that wraps the CLI and provides a `Sync(start, end) error` method.
3. Define a `MarketData` interface with methods `FetchOHLCV` and `ListTickers`.
4. Hook the module into eqats’ data‑pipeline scheduler (cron or internal job queue).
5. Write unit tests mocking the CLI to verify correct parsing.
6. Document the sync cron job in the deployment guide.

## Conclusion
Integrating bhavcopy gives eqats a reliable, low‑cost source of historical Indian equity data, freeing strategy and risk modules to focus on alpha generation and risk management.