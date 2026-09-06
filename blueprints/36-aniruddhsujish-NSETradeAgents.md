# Integration Blueprint for NSETradeAgents Features into eqats

## Overview
The NSETradeAgents repository provides a mature, production‑grade swing‑trading system for NSE small‑ and mid‑cap stocks. Its core components can be mapped onto the three eqats domains: Data Engines, Signal & Execution Logic, and Risk Engineering. Below is a concrete plan to adopt the most valuable features.

## Data Engines
- **Universe construction** – Pull the "Nifty Smallcap 250" and "Midcap 150" lists directly from NSE’s published CSV/JSON endpoints (same as `app/universe.py`). Cache the list daily and reuse for breadth calculations.
- **Breadth gate** – Compute the percentage of stocks trading above their own 50‑day SMA; skip new entries when <50 %. This can be added as a pre‑scan filter in eqats’ data‑pipeline.
- **Screener filters** – Implement the ten hard filters (price > SMA50 > SMA200, RSI 55‑70, ATR% >1.5, volume ratio >2×20‑day, day change 0.5‑8 %, 5‑day momentum >2 %, volume >50 k shares, traded value >₹2 cr, price >₹100). Each filter is a pure function on OHLCV data; they can be chained in eqats’ `SignalEngine`.
- **Fundamental check** – Retrieve market cap, debt/equity, ROE from fundamentals API (e.g., screener.in or NSE). Reject stocks with market cap <₹500 cr, debt/equity >2 (except banks), or negative ROE.
- **Decision record & dashboard** – Store every candidate’s scores, veto verdict, and eventual outcome in a time‑series table (e.g., PostgreSQL). Expose a lightweight FastAPI endpoint for the existing eqats dashboard to show live signals and veto commentary.

## Signal & Execution Logic
- **LangGraph pipeline** – Replicate the five‑node graph: `fetch_data → fundamental → market_context → technical → risk → score → veto`. Each node can be an eqats `StrategyStep` with clear inputs/outputs.
- **Scoring model** – Adopt the four‑dimension, 0‑100 additive score (entry timing 30, momentum quality 25, risk/reward 20, market regime 25). Define banding functions that map raw metrics to points; sum and compare to the 65 entry threshold.
- **Entry timing & execution** – Run the scan at 15:00 IST, generate orders, and submit them before the 15:30 close using eqats’ execution adapter (e.g., via broker API). Record the signal date as the trade’s entry day.
- **Exit management** – Implement the ATR‑based stop, trailing stop, target, and 21‑day timeout exactly as described. The trailing stop arms at 2×ATR% gain and trails 2×ATR% behind the peak; stop/target floors/caps are applied. This can live in eqats’ `RiskManager`.
- **Veto agent** – Wrap a Claude Opus ReAct agent (with Tavily search) as an optional `VetoStep`. In shadow mode it logs a verdict; in acting mode it can block the trade once the pre‑registered switch (≥30 KILLs with edge <‑4 %) is satisfied.
- **Position limits & circuit breaker** – Enforce max 5 concurrent positions, one per ticker, and pause new entries when the portfolio equity falls >8 % from its 30‑day peak.

## Risk Engineering
- **Volatility‑scaled exits** – All exit levels are expressed as multiples of ATR%, making risk proportional to each stock’s volatility. Reuse eqats’ ATR indicator to compute stop, trail, and target distances.
- **Risk/reward dimension** – The scoring already includes a risk/reward band (0‑20 points). Feed the same ATR‑based risk metrics into this dimension for consistency.
- **Portfolio‑level safeguards** – The 8 % drawdown circuit breaker and the 5‑position limit are pure risk controls; integrate them into eqats’ `PortfolioRisk` module.
- **Trade‑level sizing** – Although the original repo does not detail position sizing, eqats can adopt a fixed fractional risk per trade (e.g., 1 % of equity) using the stop distance derived from ATR% to calculate share count.

## Implementation Steps
1. **Data layer** – Add NSE universe fetcher and breadth gate to eqats’ `data_engines/universe.py`.
2. **Pre‑scan filters** – Create `data_engines/screener.py` with the ten filters and fundamental checks.
3. **Signal pipeline** – Build `signal_execution/langgraph_pipeline.py` mirroring the five‑node graph; plug in the scoring functions.
4. **Execution** – Wire the pipeline output to eqats’ `order_executor.py` with 15:00‑15:30 window logic.
5. **Exit & risk** – Implement `risk_engineering/exits.py` using ATR‑based stop/trail/target and timeout; add position‑limit and circuit‑breaker checks in `risk_engineering/portfolio.py`.
6. **Veto** – Add `signal_execution/veto.py` wrapping Claude + Tavily; expose a mode flag (`VETO_MODE=shadow|acting`) and logging to the decision‑record table.
7. **Dashboard** – Extend the existing FastAPI dashboard to display veto comments and equity curve.
8. **Testing** – Run the pipeline in simulation mode against historical NSE data; verify that the edge, win‑rate, and veto statistics match the published shadow‑mode results.
9. **Go‑live** – Once the veto shadow log shows ≥30 KILLs with edge <‑4 %, flip `VETO_MODE` to `acting` per the pre‑registered rule.

By following this blueprint, eqats can inherit a battle‑tested swing‑trading workflow, robust volatility‑scaled risk controls, and a transparent LLM‑based veto layer without rewriting core infrastructure.