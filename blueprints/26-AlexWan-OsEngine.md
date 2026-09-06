# Integration Blueprint for eqats using OsEngine

## Overview
OsEngine provides a full‑stack algo‑trading platform written in C# with .NET/WPF, an MCP AI‑agent server, data loader (OsData), backtester (OsTester), optimizer (OsOptimizer) and trader station (OsTrader). These components can be wrapped or called from eqats to extend its data, signal/execution and risk capabilities.

## Data Engines
- **OsData** – download historical candles, order‑book and tick data from MOEX, Tinkoff, ALOR, Transaq, Quik, Plaza 2, Finam, MFD, Algopack, etc. eqats can invoke OsData via its CLI or expose it as a .NET library to fill its historical store.
- **MCP API** – real‑time market data streamed over SSE with authentication and IP whitelist. eqats agents can subscribe to these feeds to keep their live market cache synchronized.
- **OsTester** – multi‑instrument, multi‑timeframe history emulator that can replay data for strategy validation. eqats can leverage OsTester as a backtesting engine, feeding it data from OsData or its own lake.
- **OsOptimizer** – walk‑forward optimization with phase‑wise filters and report generation. Useful for eqats to run automated parameter searches on strategies sourced from eqats.

## Signal & Execution Logic
- **Robot Studio (Wealth‑Lab/NinjaScript‑like)** – write C# strategy scripts that receive market events and emit orders. eqats can import these scripts as plugins or translate its own signal format into the robot interface.
- **MCP Server** – allows an AI agent (Claude, GPT, etc.) to remotely create, configure, start/stop robots, run backtests and retrieve equity curves. eqats can act as the MCP client, sending high‑level goals and receiving concrete robot configurations.
- **OsTrader (Bot station)** – executes robots against live exchange adapters (MOEX FixFast, Tinkoff API, ALOR, etc.). eqats can delegate order execution to OsTrader via its API or directly call the same adapters.
- **Event‑driven SSE** – real‑time strategy updates and order status flow via the MCP API, enabling eqats to monitor positions and adjust signals in near‑real‑time.

## Risk Engineering
- The README does not expose built‑in risk‑limit, position‑sizing or monitoring modules. Risk controls would need to be added inside the C# robot scripts (e.g., max‑loss, volatility‑based sizing) or implemented as a separate risk‑engine service that eqats calls before submitting orders via OsTrader.

## Integration Steps
1. **Expose OsEngine as a .NET NuGet package** (or use the existing binaries) so eqats can reference OsData, OsTester, OsOptimizer and the MCP server.
2. **Build a thin adapter layer** in eqats that:
   - Calls OsData to populate eqats’ historical data lake.
   - Subscribes to MCP SSE feeds for live market data.
   - Sends strategy creation requests via the MCP API to OsEngine’s robot studio.
   - Retrieves generated robot assemblies and loads them into eqats’ signal engine.
   - Routes orders from eqats to OsTrader (or directly to the exchange adapters) using the same connector interfaces.
   - Optionally invokes OsTester/OsOptimizer for strategy validation and parameter tuning.
3. **Implement risk checks** in eqats’ pre‑order pipeline (max position, VaR, leverage limits) before handing off to OsTrader.
4. **Deploy** the combined system: eqats handles high‑level strategy generation and risk management; OsEngine provides robust data ingestion, backtesting, optimization and low‑latency order routing.

## Expected Benefits
- Leverages OsEngine’s mature exchange connectors (MOEX, Tinkoff, ALOR, etc.) without re‑implementing them.
- Gains access to a proven backtesting/walk‑forward optimizer.
- Enables AI‑driven strategy discovery via MCP while retaining eqats’ own risk‑engineering rigor.
- Provides a clear migration path: existing OsEngine robots can be run unchanged, while eqats can gradually replace signal logic with its own models.
