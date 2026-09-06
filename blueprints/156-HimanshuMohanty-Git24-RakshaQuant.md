# Integration Blueprint: RakshaQuant → eqats

## Overview
RakshaQuant shows how to combine LangGraph agents, dynamic data discovery, FinOps, and realistic paper trading. The following plan adapts its strongest components for eqats.

## 1. Data Engines
- WebSocket real‑time NSE feed (IST hours) with YFinance fallback.
- Dynamic stock discovery via Google News RSS + top gainers/losers.
- Groq‑powered news sentiment cached with TTL.
- Rate limiter for Groq calls.
- PostgreSQL persistence for state, trades, lessons, FinOps logs.

## 2. Signal & Execution
- Four‑node LangGraph graph: Analyst → Formulator → Validator → Risk Guard.
- Profit‑target engine translating monthly return into required win‑rate/trade frequency.
- Closed learning loop: trade lessons stored, effectiveness measured, fed back as confidence weight.
- Signal confidence = indicator agreement × sentiment strength.
- Risk‑based sizing using account risk per trade, stop distance, optional Kelly.
- Paper engine with slippage, NSE fees, atomic PostgreSQL state.
- Live execution: shadow mode, order idempotency (UUID), broker reconciliation, kill‑switch gate.
- Telegram alerts for trades, risk, budget.
- Backtesting module using same LangGraph engine on historical data.

## 3. Risk Engineering
- Deterministic risk rules + kill switch evaluated after signal generation, before order.
- FinOps: per‑agent per‑IST‑day Groq token + cost accounting, soft/hard daily budgets, alerts, spend kill‑switch.
- Profit goal tracker (advisory only).
- Data quality: staleness gate, NaN sanitisation, indicator caching.
- Realistic trade simulation: slippage + fees, correct long/short/partial accounting.
- Execution safety: unified paper/live path, live fill lifecycle tracking.

## 4. Implementation Steps
1. Add deps: langgraph, langsmith, groq, yfinance, requests, python‑telegram‑bot, SQLAlchemy, psycopg2‑binary.
2. Build data package: WS/YFinance feed, news RSS scraper, market movers, sentiment cache, rate limiter, DB helpers.
3. Refactor strategy into LangGraph graph; move indicator logic to analyst node.
4. Implement profit‑target and learning‑loop services with DB persistence.
5. Port paper engine (slippage, fees, atomic state) and wrap in execution service supporting shadow/live.
6. Add FinOps and risk‑gate services; call before order submission.
7. Wire Telegram notifier using bot token/chat ID from env.
8. Write unit/integration tests (>300 passing), enforce ruff/flake8.
9. Run shadow‑mode trial 1‑2 weeks, validate kill‑switch and FinOps.
10. Gradually enable live orders after confirming alerts and reconciliation.

## 5. Expected Benefits
- No manual watchlist – dynamic discovery keeps universe fresh.
- LLM‑enhanced sentiment and multi‑agent reasoning improve signal quality.
- FinOps prevents unexpected Groq spend; kill switch halts LLM cycles on budget breach.
- Deterministic kill switch, shadow mode, and broker reconciliation make live deployment safe.
- Closed learning loop lets the system adapt to regime changes without human tweak.