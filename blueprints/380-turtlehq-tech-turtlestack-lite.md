# Integration Blueprint for TurtleStack Lite MCP Server into eqats

## Overview

The TurtleStack Lite repository provides a Model Context Protocol (MCP) server that unifies access to Indian stock brokers (Kite, Groww, Dhan) and offers 40+ technical indicators, real‑time trading, portfolio management and Claude AI natural‑language commands. eqats already contains a Rust core with Python/PyO3 bindings; we will integrate the MCP server as a language‑agnostic service that eqats can drive via stdio JSON‑RPC.

## Domain Mapping

- **Data Engines** – The MCP server’s technical‑indicator module and broker‑wise market‑data feeds become eqats’ *Technical Indicator Engine* and *Multi‑broker Market Data Aggregator*. These components ingest live tick data from each broker, compute indicators (RSI, MACD, Bollinger Bands, VWAP, ATR, …) and expose them through MCP indicators/* methods.

- **Signal & Execution Logic** – Strategies written in Rust/Python can request indicator values, combine them into signals, and then invoke the MCP server’s order‑management methods (placeOrder, modifyOrder, cancelOrder). The Claude AI integration is exposed as an MCP claude/* namespace, allowing natural‑language prompts to be turned into trading actions.

- **Risk Engineering** – Because the MCP server never stores API keys, credentials are supplied per‑session via the MCP authenticate method. eqats will handle credential rotation, store secrets in environment variables or a vault, and pass them to the server on each session start, satisfying the *Session‑based Authentication* and *Credential‑less Security* requirements.

## Architecture


+----------------+        stdio JSON‑RPC        +-------------------+
|  eqats (Rust)  | <====================> | TurtleStack Lite  |
|  (core + PyO3) |   MCP client (tokio)   |  (Node.js)        |
+----------------+                         +-------------------+
        ^                                       ^
        |                                       |
   Python bindings                         Broker APIs
        |                                       |
+----------------+                         +-------------------+
|  eqats‑py      |                         |  Kite / Groww /   |
|  (PyO3 wrapper)|                         |  Dhan etc.      |
+----------------+                         +-------------------+


* The Rust MCP client lives in eqats/src/mcp/turtlestack_lite.rs. It uses Tokio to spawn the Node.js server, sends/receives MCP messages, and provides async Rust functions for:
  - authenticate(broker, credentials)
  - get_indicator(broker, symbol, indicator, params)
  - place_order(broker, order)
  - modify_order(broker, order_id, changes)
  - cancel_order(broker, order_id)
  - claude_prompt(prompt)

* A thin PyO3 wrapper (eqats/python/mcp_turtlestack.py) exposes the same API to Python strategy code.

* Configuration: broker credentials are read from environment variables (KITE_API_KEY, KITE_API_SECRET, GROWW_JWT, DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID) and passed to the MCP server at session start.

* Testing: a unit test spawns the server with dummy credentials, calls get_indicator for a known symbol, and asserts that a numeric value is returned.

## Deployment

1. Add the turtlestack-lite repository as a submodule or git subtree under third_party/turtlestack-lite.
2. Ensure Node.js ≥18 is available in the runtime image.
3. Build the eqats Rust core (cargo build --release).
4. The Python package can be built with maturin and installed in the target environment.

## Safety & Compliance

- No credentials are written to disk; they are kept only in the Rust process memory.
- The MCP server’s authenticate method is called fresh for each trading session, limiting exposure.
- All communication is local stdio; no network traffic is introduced unless the broker APIs themselves are remote.

## Future Work

- Add pooling of MCP server instances for low‑latency strategies.
- Implement heartbeat/reconnect logic.
- Extend the Rust client to support MCP notifications for real‑time ticker updates.
