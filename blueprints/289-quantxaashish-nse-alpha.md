# Integration Blueprint for nse-alpha Features into eqats

## Overview
The nse-alpha repository provides a robust, research‑grade pipeline for cross‑sectional alpha generation in Indian equities. Its clean separation of data ingestion, signal library, evaluation engine, and reporting can be leveraged to enhance eqats’ data engines, signal/execution logic, and risk‑engineering layers.

## Data Engines
- **Ingestion & Caching**: Adopt `ingest.py` (yfinance + backoff) to pull daily OHLCV for any equity universe, writing raw files to a version‑controlled Parquet lake via `cache.py`. This mirrors eqats’ desire for immutable, snapshotted market data.
- **Panel Construction**: Use `panel.py` to assemble a MultiIndexed (date, symbol) panel, enabling fast vectorised look‑ups across eqats’ signal‑generation functions.
- **Universe Management**: Re‑use the static‑CSV universe loader (`nifty200.py`) and liquidity filter as a starting point for eqats’ universe service; integrate the point‑in‑time stub (`universe/point_in_time.py`) to eliminate survivorship bias when historical index constituents become available.

## Signal & Execution Logic
- **Signal Registry**: Implement a decorator‑based registry similar to `signals/registry.py` that forces each new alpha to include a rationale, family tag, and unit‑tested output (a Series indexed by date and symbol). This would standardise eqats’ signal contributions and improve discoverability.
- **Pre‑processing Pipeline**: Plug in the existing winsorise → z‑score → sector‑neutralisation steps from `preprocessing.py` as a reusable transformer that eqats can apply before any model‑specific weighting.
- **Alignment Layer**: Enforce a fixed one‑day shift (IMPLEMENTATION_GAP = 1) exclusively in `alignment.py` to guarantee leak‑free feature/target alignment—a practice eqats can adopt across all pipelines.
- **IC & Risk‑Adjusted Metrics**: Use the Spearman IC with Newey‑West HAC (`ic.py`) and the decile equal‑weight long/short construction (`portfolio.py`) as reference implementations for eqats’ factor evaluation suite.
- **Turnover & Cost Modelling**: Integrate `turnover.py` (mean absolute weight change / 2) and `costs.py` (configurable round‑trip bps) to produce net‑Sharpe metrics at multiple cost levels, directly feeding eqats’ risk‑adjusted performance dashboard.
- **Walk‑Forward Validation**: Adopt the `WalkForwardEmbargo` protocol from `validation.py` for expanding‑window cross‑validation, ensuring that eqats’ strategy research respects an embargo period to mitigate over‑fitting.
- **Reporting**: Re‑use the reporting stack (`table.py`, `plots.py`, `markdown.py`) to auto‑generate an alpha‑table CSV, IC decay plots, quantile return charts, and cumulative L/S equity curves, complete with a survivorship‑bias note.

## Risk Engineering
- **Cost Sensitivity**: Expose net‑Sharpe at 5, 15, and 30 bps (as in nse-alpha) as standard risk‑adjusted outputs, allowing eqats to quickly assess strategy robustness under varying transaction‑cost assumptions.
- **Turnover Monitoring**: Incorporate the turnover metric as a risk limit signal; eqats can trigger rebalancing alerts or position‑size scaling when turnover exceeds a threshold.
- **Walk‑Forward Embargo**: Treat the embargo period as a risk control that reduces look‑ahead bias, analogous to a max‑drawdown or VaR limit in the research phase.
- **Future Extensions**: When eqats adds factor risk neutralisation or nonlinear impact models (Almgren‑Chriss), the existing stubs in `eval/validation.py` and the roadmap in nse-alpha provide a clear migration path.

## Integration Steps
1. Fork the nse-alpha codebase into eqats’ `contrib/nse_alpha` directory.
2. Create a thin adapter layer that maps eqats’ configuration (universe, date range, cost bps) to the nse-alpha CLI (`nse-alpha run`/`report`).
3. Replace the static universe loader with eqats’ dynamic universe service while preserving the same interface (returns a list of symbols for a given date).
4. Register eqats’ proprietary signals via the `registry.py` decorator, ensuring each signal includes a rationale and family tag.
5. Run the canary test suite (`tests/test_canaries.py`) as a gate‑keeping step in eqats’ CI before any signal is promoted to production.
6. Generate the alpha‑table and associated plots; ingest them into eqats’ research database for further meta‑analysis and strategy allocation.

By incorporating these components, eqats gains a battle‑tested, leak‑free data pipeline, a standardized signal development framework, and transparent cost‑adjusted performance reporting—all critical for institutional‑grade quantitative research.
