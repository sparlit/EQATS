# Integration Blueprint: nse-momentum-dashboard → eqats

## Summary
The nse-momentum-dashboard provides a complete, deterministic momentum‑plus‑quality screening and execution system built on Streamlit and Kite Connect. Its most valuable pieces can be lifted into eqats to add a robust NSE‑focused momentum strategy, automated GTT stop‑loss handling, and a transparent propose‑review‑execute workflow.

## Data Engines
- Live NSE F&O universe fetcher (fno_universe.py) that calls https://www.nseindia.com/api/underlying-information, adds browser‑like headers, handles cookies, and caches the result weekly. A fallback snapshot guarantees availability when NSE is unreachable.
- Kite Connect historical data pipeline – the app pulls daily OHLCV for each symbol via Kite’s historical API and stores it locally (or in memory) for indicator calculations.
- SQLite state database (state.db) that persists Kite API credentials (encrypted as needed) and runtime state such as open slots, positions, and last rebalance timestamp.
- Configurable universe override via config.UNIVERSE_OVERRIDE allowing eqats to plug in its own symbol list (e.g., EQTS‑specific universes).

These components map directly onto eqats’ data‑engine layer: replace or complement the existing market‑data ingest with the NSE‑universe fetcher, reuse the caching strategy, and adopt the SQLite state pattern for credential and strategy state management.

## Signal & Execution Logic
- Composite momentum‑quality score – 40% 6‑month relative strength, 25% 3‑month RS, 20% proximity to 52‑week high, 15% 20‑day vs 60‑day volume expansion (all z‑scored). This formula can be imported as a pure‑Python function.
- Deterministic gates – trend (close > 50 EMA > rising and > 200 EMA), 52‑week high ≥ 85%, RSI(14) between 45‑78, quality gate (XBRL fundamental score ≥ threshold). Each gate is a separate, testable predicate.
- Calendar‑entry slot filling – whenever a slot becomes free (monthly rebalance or mid‑month stop‑loss trigger) the highest‑ranking gate‑passer is immediately inserted, eliminating latency.
- Monthly rebalance logic – exit any position that falls below its 200 EMA or drops out of the top 2xmax_positions ranking.
- Backtest engine – a vectorized backtest that walks forward through historical data, applies the same scoring/gating rules, and records P&L, useful for eqats’ research pipeline.
- Order execution via Kite – market or limit orders are placed through the Kite SDK; stop‑losses are submitted as GTT (Good‑Till‑Triggered) orders so they survive across sessions and system restarts.
- Propose‑review‑execute workflow – a Streamlit‑based UI that lists candidate trades, lets a human reviewer approve or reject, then executes the approved batch. The same pattern can be wrapped in eqats’ approval microservice or CLI.

Integrating these into eqats means:
1. Adding the scoring/gating module as a strategy plugin.
2. Re‑using the slot‑manager logic for eqats’ position‑limit engine.
3. Adopting the GTT order wrapper for eqats’ execution adapter.
4. Exposing the propose‑review‑execute UI as an optional admin dashboard or extending eqats’ existing UI.

## Risk Engineering
- ATR‑based stop loss – stop price = entry - 2.5xATR(14), submitted as a GTT order; the stop persists even if the dashboard is restarted.
- RSI entry ceiling – no new entries when RSI > 78, preventing overextended buys.
- Equal‑risk position sizing – qty = (risk_per_trade_pct% of capital) / (entry - stop). This ensures each trade risks the same fraction of equity.
- Volume confirmation filter – requires 20‑day average volume > 60‑day average volume (expansion) contributing to the score.
- Quality gate – fundamental XBRL score threshold eliminates low‑quality names, reducing crash susceptibility.
- Momentum‑crash mitigations – the combination of RSI cap, ATR stop, and quality gate directly addresses the failure modes highlighted by Daniel & Moskowitz (2016).

These risk controls can be ported to eqats’ risk‑engineering layer:
- Replace or augment existing stop‑loss logic with the ATR‑GTT wrapper.
- Plug the equal‑risk sizing function into eqats’ position‑sizing service.
- Add the RSI and volume filters as pre‑trade sanity checks.
- Incorporate the fundamental quality score as an additional factor in eqats’ existing fundamental model.

## Implementation Steps
1. Extract fno_universe.py, scoring functions, gating predicates, and position‑sizing utilities into a shared Python package.
2. Create an eqats adapter that calls the NSE universe fetcher (or uses eqats’ own universe) and feeds symbols into the scoring module.
3. Integrate the GTT order helper with eqats’ broker abstraction (Kite or other) so stop‑losses are submitted as GTT orders.
4. Expose a lightweight Streamlit (or FastAPI‑based) UI for the propose‑review‑execute flow, or reuse eqats’ existing UI components.
5. Add unit tests for each gate, scoring, and sizing function to guarantee determinism.
6. Run the existing backtest engine on eqats’ historical data to validate performance before live deployment.

By incorporating these modules, eqats gains a battle‑tested, rule‑based momentum strategy with built‑in crash protection, automated stop‑loss persistence, and a clear human‑in‑the‑loop execution process—all without relying on AI/LLM components.