Integration Blueprint for eqats

### 1. Data Engine Enhancements
- Adopt the normalized `MarketTick` schema to decouple ingestion from provider-specific code, enabling easy addition of new data sources (e.g., other brokers or simulated feeds).
- Implement candle aggregation utilities (1/3/5/15/30 min) with IST timezone handling, gap filling, and duplicate‑tick detection as shown in the repo.
- Provide three operating modes – `mock`, `live`, and `replay` – to support development, production, and historical strategy testing without changing core logic.
- Use a WebSocket fan‑out pattern: a single persistent Kite (or eqats) connection runs in the backend, broadcasting a compact JSON payload (~250 ms batch) to all connected front‑ends or internal services.
- Leverage async, non‑blocking processing with incremental indicator updates and batched broadcasts to keep CPU usage low.
- Add robust reconnect logic with exponential backoff, automatic resubscription, heartbeat monitoring, and stale‑data detection.

### 2. Signal & Execution Logic Additions
- Import the five intraday strategies (ORB 15‑min, VWAP mean‑reversion, Supertrend‑flip momentum, Gap‑and‑Go/Gap‑Fade, first VWAP pullback) from `backend/app/intraday_strategies.py`. Each strategy already computes live entry, stop, target and tracks a same‑session hit‑rate; they can be registered as plug‑in modules in eqats’ strategy engine.
- Integrate the OHLC Breaker state machine (`backend/app/breaker.py`) to generate breakout/breakdown signals gated on RVOL≥1.5× and ADX≥20, outputting ATR‑sized entry/stop/target and a 0‑100 breakout score.
- Bring in the options strategy panel (`backend/app/options/strategies.py`) to eqats’ options‑trading suite: short strangle, iron condor, credit spreads, iron fly, calendar, 1x2 ratio spread, each priced live from the option chain with net premium, max P/L, breakevens, risk‑neutral POP, theta, and margin estimate.
- Add the Seller’s Premium Dashboard metrics (VIX z‑score, IV‑minus‑RV spread, premium‑selling favorability score, expiry‑day pin risk) to eqats’ risk‑monitoring dashboard.
- Expose the configurable 0‑100 analytical score (Momentum 25 + Volume 25 + RelVolume 20 + Breakout 15 + VWAP 10 + Volatility 5) as a generic scoring framework that eqats can weight per‑asset class.
- Implement the alert system with cooldown/debounce for breakout, breakdown, volume spike, VWAP cross, momentum, RSI, and percent‑movement events, feeding eqats’ notification service.
- Reuse the frontend components (FilterBuilder.jsx, detail panel, market overview) as inspiration for eqats’ UI: collapsible dashboards, reorderable/pinnable columns, sector filters, and real‑time charts via Recharts or eqats’ preferred charting library.

### 3. Risk Engineering Contributions
- Use the `atr_stop_target()` function to size stop‑loss and target levels for every generated signal, tying risk directly to market volatility.
- Derive position‑size recommendations from ATR and a user‑defined risk‑per‑trade percentage; this can be mapped onto eqats’ risk‑limit engine.
- Incorporate the options risk metrics (max profit/loss, breakevens, margin estimate, theta, risk‑neutral POP) into eqats’ options‑risk module, and gate strategy selection on IV rank and ADX thresholds as done in the source repo.
- Adopt the market‑status monitor (NSE hours, holidays, LIVE/DELAYED/STALE/NO_DATA) and data‑freshness timestamps to drive eqats’ operational health checks.
- Apply alert cooldown/debounce logic to prevent over‑trading and notification fatigue.
- Ensure all logging is structured and free of secrets, facilitating audit trails and compliance.

### 4. Suggested Implementation Steps
1. **Data Layer** – Copy `MarketTick` definition, candle aggregator, and WebSocket wrapper into eqats’ `data_ingest` package; add mode flags (`mock/live/replay`).
2. **Strategy Engine** – Register the five intraday strategies and the OHLC Breaker as strategy plugins; expose their outputs via eqats’ signal bus.
3. **Options Module** – Import the options strategy calculations and seller‑premium metrics; integrate with eqats’ option‑chain feeder and risk engine.
4. **Scoring & Alerts** – Implement the configurable score formula and alert debouncer; hook into eqats’ notification service.
5. **UI/UX** – Use the frontend component ideas to enhance eqats’ dashboard: collapsible drawers, column pinning, sector multi‑select, and real‑time charts.
6. **Risk Controls** – Wire ATR‑based sizing, IV/ADX gating, and market‑status checks into eqats’ risk‑limit and position‑sizing services.
7. **Testing** – Leverage the existing unit tests and synthetic end‑to‑end runs to validate each imported module against eqats’ data formats.

By following this blueprint, eqats can gain a production‑grade real‑time ingestion pipeline, a rich library of intraday and options strategies, and robust risk‑sizing and monitoring tools—all built on battle‑tested, transparent code that avoids fabricated data.