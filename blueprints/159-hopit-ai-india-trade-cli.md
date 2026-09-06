# Integration Blueprint: Vibe Trading Features into eqats

## Overview
Vibe Trading provides an agentic multi‑agent analysis pipeline, live Indian‑market data ingestion, and risk‑profiled trade plan generation. The following blueprint maps its most valuable components to the eqats architecture.

## Data Engines
- **Live market data connector** – Adapt the Fyers WebSocket/REST client to feed real‑time quotes, options chain, GEX, and IV data into eqats’ market‑data engine. Keep the existing yfinance fallback for delayed data.
- **Options scanner** – Reuse the OI‑based scanner to generate option‑flow signals that can be consumed by eqats’ signal layer.
- **Fundamental & news feeds** – Plug the fundamental analyst’s data pull (financial statements, sector rotation) and news/macro collector into eqats’ fundamental and alternative‑data pipelines.
- **Storage** – Store raw ticks and derived indicators in eqats’ time‑series database (e.g., TimescaleDB) using the same schema as the existing market‑data module.

## Signal & Execution Logic
- **Multi‑agent analyst pool** – Implement seven analyst agents as stateless microservices (or eqats strategy modules) that receive the same market data snapshot and return a structured signal (score, confidence, rationale). Use eqats’ plugin system to register each analyst.
- **Weighted scorecard & conflict detection** – Create a signal‑aggregation component that computes a weighted average of analyst scores and flags conflicts when bull/bear scores diverge beyond a threshold.
- **Multi‑round debate engine** – Orchestrate a debate loop (bull → bear → rebuttal ×2 → facilitator) using eqats’ workflow manager; each round calls the LLM with a tailored prompt. The final fund‑manager synthesis step produces a consensus signal (BUY/SELL/HOLD) with confidence.
- **Trade‑plan generator** – Translate the consensus signal into three risk‑profiled order tickets (entry, stop, target, size) matching eqats’ order‑ticket format. Reuse the existing position‑sizing module but allow the risk‑manager agent to override parameters.
- **Live execution** – Connect eqats’ order‑gateway to Zerodha (via Kite Connect) and Fyers (for market data) using the same API keys; leverage eqats’ broker‑adapter pattern.
- **CLI & app integration** – Expose the pipeline through eqats’ CLI (`eqats analyze <symbol>`) and optionally through the Electron‑based dashboard, reusing the FastAPI sidecar for streaming updates.

## Risk Engineering
- **Risk‑manager agent** – Implement as a dedicated eqats risk‑module that receives the consensus signal and outputs stop‑loss, target levels, and position size based on volatility (ATR) and account equity.
- **Risk profiles** – Package the aggressive/neutral/conservative presets as configurable risk‑profile objects that can be selected at runtime via eqats’ config or CLI flag.
- **Pre‑trade checks** – Use the risk‑manager’s output to perform margin, funds, and max‑loss validation before submitting orders through eqats’ execution engine.
- **Post‑trade monitoring** – Extend eqats’ monitoring service to track realized P/L against the planned stop/target and emit alerts (Telegram, Discord) similar to Vibe Trading’s alerting.

## Implementation Steps
1. **Data layer** – Add Fyers client plugin; configure fallback to yfinance.
2. **Signal layer** – Create seven analyst plugins; define common signal interface.
3. **Aggregation layer** – Build scorecard, conflict detector, debate orchestrator, and trade‑plan generator.
4. **Execution layer** – Wire Zerodha adapter; reuse eqats’ order‑ticket and risk‑checks.
5. **UI/CLI** – Register new `analyze` command; optionally enable Electron dashboard.
6. **Testing** – Run paper‑trading mode with historical data; validate debate logic and risk‑plan outputs.
6. **Deployment** – Package as eqats extension; update documentation and CI.

## Expected Benefits
- Institutional‑grade, multi‑perspective analysis for Indian equities and derivatives.
- Transparent LLM‑driven debate that improves signal robustness.
- Ready‑to‑use risk‑profiled trade plans reducing manual position‑sizing effort.
- Seamless live‑trading capability via Indian brokers without leaving the eqats ecosystem.