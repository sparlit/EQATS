# Integration Blueprint for eqats from kraken-cli

## Overview
kraken-cli is an AI-native command‑line interface that provides unified access to Kraken’s spot, tokenized stocks, forex, futures, and earn products. It emphasizes structured JSON output, agent‑first design, paper trading, and built‑in MCP server capabilities.

## Data Engines
- **Real‑time market data ingestion**: `kraken ticker`, order book, and trade history endpoints deliver live prices for all supported asset classes.
- **Historical data retrieval**: CLI can fetch past candles and trade logs via Kraken API, enabling back‑test research.
- **Workspaces & Sessions**: Users can isolate research contexts, store notes, and replay market data streams, which can be mapped to eqats’ data lake or feature store.
- **MCP Server**: The built‑in Model Context Protocol server exposes market data as resources that AI agents can subscribe to, providing a push‑based feed for eqats’ signal generators.

## Signal & Execution Logic
- **Unified order interface**: Single `kraken order` command works across crypto spot, tokenized assets, forex, perpetual and fixed‑date futures, with `--asset-class` flag.
- **Paper trading mode**: `kraken paper` lets agents test strategies against live prices without risk, ideal for eqats’ strategy validation pipeline.
- **Advanced order types**: Limit, market, trailing stop, and leveraged positions (up to 50× on futures) are directly supported.
- **Skill workflows**: The `skills/` directory contains SKILL.md files that encapsulate end‑to‑end trading routines (e.g., “morning market brief”, “leveraged long with trailing stop”). These can be imported as eqats strategy templates.
- **Agent‑first tooling**: `agents/tool-catalog.json` provides 174 command schemas with types and safety flags; `AGENTS.md` details authentication, invocation, error handling, and rate limits. eqats can generate RPC calls to the CLI using this catalog.
- **MCP integration**: By running the CLI’s MCP server, eqats agents can subscribe to market data resources and invoke trading tools via standardized MCP calls.

## Risk Engineering
- **Leverage & margin limits**: The CLI enforces Kraken‑defined maxima (10× spot, 3× tokenized stocks, 50× perpetual futures, etc.) and surfaces them via error envelopes.
- **Trailing stop & risk‑aware orders**: Built‑in trailing‑stop functionality allows automatic risk‑adjusted exits.
- **Error catalog**: `agents/error-catalog.json` categorizes failures (auth, rate_limit, validation, api, network) with retry guidance, enabling eqats’ risk manager to implement circuit‑breakers and back‑off policies.
- **Paper trading sandbox**: Provides a zero‑capital environment for validating position sizing, stop‑loss, and leverage before live deployment.
- **Safety flags in tool catalog**: Each command includes a safety flag (e.g., `high_leverage`, `market_order`) that eqats can use to gate or require additional approvals.
- **Rate‑limit awareness**: Structured JSON errors include a `rate_limit` type, letting eqats throttle requests automatically.

## Integration Steps for eqats
1. **Wrap kraken-cli as a service**: Deploy the binary alongside eqats’ runtime and expose a thin REST/gRPC layer that translates eqats internal signals to `kraken` CLI calls (using the JSON‑only mode `-o json`).
2. **Leverage the tool catalog**: Auto‑generate eqats adapter functions from `agents/tool-catalog.json` to guarantee type‑safe invocations.
3. **Subscribe to market data via MCP**: Start the CLI’s MCP server (`kraken mcp server`) and have eqats’ data engine connect as an MCP client to receive real‑time ticker, order‑book, and trade streams.
4. **Deploy skill libraries**: Clone the `skills/` directory into eqats’ strategy repository; each SKILL.md can be rendered into a parameterized strategy template.
5. **Implement risk layer**: Map the leverage limits and safety flags from the CLI into eqats’ risk engine; use the error catalog to drive retry, escalation, and kill‑switch logic.
6. **Validate with paper trading**: Before any live capital allocation, run the strategy through `kraken paper` to verify P&L, slippage, and risk‑metric behavior.
7. **Monitor & audit**: Capture the CLI’s JSON stdout/stderr logs; forward them to eqats’ observability pipeline for audit trails and performance analytics.

## Benefits
- **Unified multi‑asset access** eliminates the need for separate exchange adapters.
- **Agent‑first design** aligns with eqats’ goal of LLM‑driven trading bots.
- **Structured JSON & MCP** reduce parsing complexity and enable real‑time data push.
- **Paper trading & skill catalog** accelerate strategy development while keeping risk under control.
