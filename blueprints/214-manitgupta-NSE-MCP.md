# Integrating NSE-MCP Data Engine into eqats

## Overview
The `manitgupta/NSE-MCP` repository provides an MCP server that exposes live Indian stock market data from NSE via a stdio‑based interface. It offers 17 typed tools covering bulk/block/insider deals, FII/DII activity, quotes, indices, gainers/losers, most active, corporate announcements, actions, and short selling data. The server handles NSE session authentication automatically and caches cookies for ~7 minutes.

## Integration Strategy
Because eqats is a quantitative trading system that already expects data feeds, we can treat the NSE‑MCP server as a **data engine** plug‑in. Two approaches are possible:

1. **Direct stdio invocation** – spawn the compiled `dist/index.js` as a child process and communicate via MCP messages (JSON‑RPC style) using an MCP client library (e.g., `@modelcontextprotocol/sdk`).
2. **Wrapper service** – run the MCP server continuously and expose a thin HTTP/WS API (or reuse its stdio via a local socket) that eqats’ data‑ingestion layer polls.

Given the server’s lightweight nature and lack of external configuration, the stdio approach minimizes operational overhead.

## Step‑by‑Step Integration

### 1. Add the repository as a dependency
```bash
# Inside eqats repo
git submodule add https://github.com/manitgupta/nse-mcp.git vendors/nse-mcp
cd vendors/nse-mcp
npm ci
npm run build
cd ../..
```

### 2. Initialize an MCP client in eqats (TypeScript example)
```ts
import { spawn } from 'child_process';
import { MCPClient } from '@modelcontextprotocol/sdk'; // hypothetical MCP client

const nseMcp = spawn('node', [
  `${__dirname}/vendors/nse-mcp/dist/index.js`
], { stdio: ['pipe', 'pipe', 'pipe'] });

const client = new MCPClient({
  getReader: () => nseMcp.stdout,
  getWriter: () => nseMcp.stdin
});

await client.initialize();
```

### 3. Fetch data using the exposed tools
```ts
// Example: get a quote for RELIANCE
const quote = await client.callTool('get_quote', { symbol: 'RELIANCE' });
console.log(quote);

// Example: get today's bulk buys
const topBuys = await client.callTool('get_top_bulk_buys', { limit: 20 });
```

### 4. Handle session‑UA override (if needed)
```ts
const env = { NSE_MCP_UA: 'Mozilla/5.0 (custom)' };
const nseMcp = spawn('node', [
  `${__dirname}/vendors/nse-mcp/dist/index.js`
], { stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ...env } });
```

### 5. Integrate into eqats’ data pipeline
- **Market data feed**: Call `get_quote` or `get_market_status` on a subscription basis (e.g., every 5 seconds) to update the internal tick store.
- **Flow signals**: Use `get_fii_dii_activity` to derive net inflow/outflow features for regime detection.
- **Insider/block deals**: Feed `get_insider_trading`, `get_block_deals`, `get_bulk_deals` into event‑driven signal generators (e.g., spike detection).
- **Short‑selling monitor**: Periodically call `get_short_selling` to flag stocks with rising short interest for risk checks.
- **Corporate actions**: Use `get_corporate_actions` and `get_nse_announcements` to adjust positions for dividends, splits, bonuses.

### 6. Error handling & resilience
- The MCP server automatically refreshes NSE session cookies every ~7 minutes; eqats should treat any `null` or error response as a transient failure and retry with exponential back‑off.
- Monitor child‑process health; restart if the stdio channel closes unexpectedly.
- Respect NSE’s rate limits: the server already throttles via session caching; avoid calling tools more than once per second per symbol.

## Benefits
- **Zero‑cost data source**: No API keys or subscriptions required; relies on NSE’s public endpoints.
- **Typed JSON**: Guarantees schema consistency, simplifying validation in eqats.
- **Unified interface**: All relevant Indian equity data categories are accessible through a single MCP endpoint, reducing integration surface.
- **Session handling built‑in**: No need to manage cookies or headers manually.

## Considerations
- The server is pure data; eqats must implement its own signal generation, execution, and risk layers on top of the fetched data.
- Since the repo has only 12 stars and limited community support, eqats should vendor the code (as shown) to avoid upstream breakage.
- If eqats already runs a Node.js environment, the MCP server can be required as a module instead of spawning a child process, further reducing latency.

## Conclusion
By wrapping `manitgupta/NSE-MCP` as a stdio‑based MCP data engine, eqats gains reliable, real‑time Indian market data with minimal development effort. The data can flow directly into eqats’ storage layer, fueling downstream signal & execution logic and risk‑engineering modules without worrying about authentication or low‑level API details.
