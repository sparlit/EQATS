# Integration Blueprint: DailyVaultRates → eqats

## Overview
DailyVaultRates is a Next.js 14 TypeScript dashboard that provides real‑time precious‑metal, Indian equity and forex rates, plus analytical tools such as PDF export and a jewelry estimator. While it does not contain signal generation or order execution logic, its data‑engine capabilities are directly reusable in the eqats project for market‑data ingestion and visualization.

## Data Engine Features to Reuse
- **Precious Metals Vault** – real‑time spot rates for Gold 24K/22K/18K, Silver 999, Platinum, Aluminum (IBJA aligned).
  *Integration*: Wrap the existing fetch logic (likely using `yahoo-finance2` or a custom API) into a reusable eqats market‑data adapter that publishes to a shared Redis/Kafka stream under the topic `metals.spot`.
- **Live Indian Stock Tracker** – 10‑second polling of NSE/BSE equities with fuzzy search (Command‑K).
  *Integration*: Replace the polling with a subscription to eqats’ low‑latency equity feed (e.g., WebSocket from a broker or exchange). Keep the SWR‑based caching layer for UI components.
- **Global Forex Exchange** – real‑time currency matrix vs INR/USD.
  *Integration*: Extend the fx adapter to ingest from eqats’ FX engine and expose the same matrix format for the UI.
- **Yahoo‑finance2 + SWR** – data fetching and client‑side caching.
  *Integration*: Use SWR as the client‑side hook in eqats’ React components; keep the server‑side fetching via Next.js Server Actions or eqats’ internal micro‑service.
- **Executive PDF Export** – one‑click PDF report generation.
  *Integration*: Leverage the same PDF‑generation library (likely `jsPDF` or `pdfkit`) to create eqats strategy‑performance reports and risk‑summary sheets.

## Signal & Execution Logic
DailyVaultRates does not contain any signal generation, strategy back‑testing, or order‑execution modules. To bring this domain into eqats, consider:
- Adding a **Signal Layer** that consumes the real‑time metal/equity/fx streams and emits trading signals (e.g., mean‑reversion on gold‑silver ratio, momentum on NIFTY).
- Building an **Execution Adapter** that routes signals to eqats’ order‑management system (OMS) via REST/FIX.
These components would sit alongside the existing dashboard without modifying its core UI.

## Risk Engineering
No explicit risk‑limits, position‑sizing, or monitoring features are present. When integrating, eqats should:
- Apply its existing **risk‑engine** (VaR, leverage caps, stop‑loss) to any signals derived from the imported data streams.
- Use the dashboard’s **overview drawer** (52‑week position slider, key ratios) as a visual risk‑monitoring widget, feeding it real‑time risk metrics from eqats’ risk service.
- Implement **alerting** (e.g., email via Brevo) for risk‑limit breaches, mirroring the existing 3:35 PM IST closing digest.

## Implementation Steps
1. **Fork** the DailyVaultRates repo and rename to `eqats-dashboard`.
2. **Extract** data‑fetching utilities into a `/lib/marketData` folder; replace direct `yahoo-finance2` calls with a thin wrapper that subscribes to eqats’ internal data topics (Redis pub/sub or Kafka).
3. **Update** SWR hooks to use the new wrapper; keep the same caching strategy.
4. **Adapt** the PDF export module to accept eqats‑generated JSON reports (e.g., strategy performance, risk summary).
5. **Add** a new `/src/signal` folder containing placeholder signal‑generation functions that consume the market‑data streams.
6. **Wire** the signal folder to an execution adapter in `/src/execution` that communicates with eqats’ OMS.
7. **Integrate** risk‑monitoring widgets: modify the overview drawer to display VaR, leverage, and margin‑call metrics pulled from eqats’ risk service via an API route.
8. **Configure** GitHub Actions to run eqats’ CI pipeline (lint, test, build) alongside the existing PR checks.
9. **Deploy** to Vercel (or eqats’ preferred hosting) and verify real‑time updates match eqats’ backend frequencies.
10. **Document** the integration in `README.md` with a section “eqats Integration” and update contributing guidelines.

## Expected Benefits
- Immediate access to institutional‑grade precious‑metal, Indian equity and forex feeds without building new connectors.
- A polished, responsive UI for traders to visualize eqats‑generated signals and risk metrics.
- Reuse of proven PDF‑export and email‑digest infrastructure for automated reporting.
- Reduced time‑to‑market for new quantitative strategies that focus on metals, equities, or FX.