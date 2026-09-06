# Integration Blueprint: Live NSE/BSE MCP Server into eqats

## Overview
The Live-NSE-BSE-MCP repository provides a Model Context Protocol (MCP) server that streams live Indian stock market data (BSE & NSE) via the IndianAPI. It offers real‑time quotes, market news, IPO lists, top performing stocks, mutual funds, and ETFs through both HTTP and stdio transports.

## Relevant Features for eqats
- **Data Ingestion**: Access to live market data, news, corporate actions, and fund information for Indian exchanges.
- **Transport Flexibility**: Can be consumed via stdio (ideal for direct MCP clients) or HTTP (for web‑based services).
- **Configuration**: Simple environment‑variable driven setup (API key, host, port, timeout, log level).

## How to Integrate as a Data Engine in eqats
1. **Add a new connector** (`eqats/connectors/ise_mcp.py`) that implements eqats’ `MarketDataProvider` interface.
2. **Stdio mode** (recommended for low‑latency, in‑process usage):
   - Launch the MCP server as a subprocess using `python -m ise_mcp.stdio_server`.
   - Communicate over stdin/stdout with JSON‑RPC messages defined by the MCP spec.
   - The connector sends requests like `{"method":"get_quote","params":{"symbol":"RELIANCE"}}` and parses the response.
3. **HTTP mode** (for micro‑service or remote deployment):
   - Start the server with `python -m ise_mcp.server` (defaults to `http://localhost:8000`).
   - The connector issues standard HTTP GET/POST to endpoints such as `/quote`, `/news`, `/ipo`, etc.
4. **Configuration**:
   - Export `ISE_API_KEY` (from IndianAPI) in eqats’ environment.
   - Optionally override `ISE_HTTP_HOST`, `ISE_HTTP_PORT`, `ISE_REQUEST_TIMEOUT`, `ISE_LOG_LEVEL`.
5. **Error handling & retries**:
   - Respect the server’s `ISE_REQUEST_TIMEOUT`.
   - Implement exponential backoff on HTTP 5xx or MCP error responses.
6. **Testing**:
   - Use the provided `.env.example` to create a test configuration.
   - Run the server in stdio mode within eqats’ test suite to verify connector logic.

## Usage Example (pseudo‑code)
```python
from eqats.connectors.ise_mcp import ISE_MCPConnector

provider = ISE_MCPConnector()
quote = provider.get_quote("RELIANCE.NS")
news = provider.get_latest_news(limit=5)
```

## Benefits for eqats
- Enables strategies that require Indian‑market live data without building a custom API client.
- Leverages the MCP standard, making the connector reusable across other MCP‑compatible hosts (e.g., Claude Desktop, custom IDEs).
- Provides a ready‑made source for news and corporate‑event data that can feed signal generation or risk‑monitoring modules.

## Limitations & Notes
- The repository does **not** contain signal generation, order execution, or risk‑management logic; those must be supplied by eqats’ existing modules.
- The server depends on a valid IndianAPI key; rate limits and data availability are governed by that service.
- Since the package is not yet on PyPI, eqats should install it from source or bundle the code as a vendor dependency.

## Deployment Steps
1. Clone the repo inside eqats’ `vendor/` directory or add as a git submodule.
2. Run `pip install -e ./vendor/Live-NSE-BSE-MCP` (or add to `requirements.txt`).
3. Ensure the `.env` file with `ISE_API_KEY` is present in the runtime environment.
4. Start the MCP server as part of eqats’ service orchestration (Docker Compose, Kubernetes, or local dev script).
5. Point eqats’ data‑engine configuration to use the new ISE_MCPConnector.

## Conclusion
By treating the Live-NSE-BSE-MCP server as a dedicated data‑engine plugin, eqats can instantly gain access to comprehensive, real‑time Indian equity and fund data, enriching its strategy research, backtesting, and live‑trading pipelines while keeping signal, execution, and risk logic within its own core.
