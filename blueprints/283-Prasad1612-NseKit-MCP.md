# Integration Blueprint: NseKit-MCP with eqats

## Overview
NseKit-MCP is a FastMCP server that provides over 100 tools for accessing live and historical data from the National Stock Exchange of India (NSE). It can be used as a data engine within the eqats quantitative trading platform to feed market data into signal generation, execution, and risk modules.

## Integration Steps

1. **Deploy NseKit-MCP**
   - Install `uv` if not present.
   - Add the server to your MCP configuration using the command `uvx` and argument `nsekit-mcp@latest`.
   - Verify the server is reachable via your MCP client (Claude Desktop, Cursor, etc.).

2. **Create a Data Adapter in eqats**
   - Implement a thin wrapper that calls the desired NseKit-MCP tools via the MCP protocol.
   - Example pseudo‑code:
     ```
     async def fetch_equity_live(symbol):
         result = await mcp.call_tool('equity_live_stock_info', {'symbol': symbol})
         return result
     ```
   - Map each tool’s JSON output to eqats’ internal market‑data schema (timestamp, open, high, low, close, volume).

3. **Data Engine Registration**
   - Register the adapter as a data source in eqats’ data‑engine layer.
   - Configure subscription intervals (live ticker every second, end‑of‑day bhavcopy once daily) respecting the built‑in rate limit (~3 requests/sec).

4. **Signal & Execution Logic**
   - Feed the live equity and option‑chain data into existing eqats strategy modules.
   - Use `fno_live_option_chain` for IV, PCR, Max Pain to enrich feature sets.
   - Use `equity_52week_high_live` or `equity_live_stock_info` for breakout/mean‑reversion signals.

5. **Risk Engineering**
   - Pull `fii_dii_activity` and bulk/block deals to monitor institutional flow.
   - Use `equity_eod_bhavcopy_delivery` for delivery‑percentage based risk filters.
   - Leverage the server’s thread‑safe rate limiting to ensure compliance with NSE usage policies.

## Benefits
- Comprehensive coverage: access to 100+ NSE data points without maintaining separate APIs.
- Built‑in safety: rate limiting and JSON‑only output reduce integration errors.
- AI‑agent friendly: works seamlessly with MCP‑compatible assistants, enabling natural‑language data queries within eqats notebooks or dashboards.
- Extensibility: new NseKit releases automatically expand the tool set.

## Considerations
- The repository supplies only data; signal generation, order execution, and risk calculations must be implemented in eqats.
- Ensure the MCP client used by eqats supports asynchronous calls to avoid blocking the main trading loop.
- Periodically verify that the `nsekit-mcp@latest` package is up‑to‑date to capture new NSE endpoints.

## Example Workflow
1. At market open, eqats calls `market_live_status` to confirm NSE is open.
2. For each ticker in the watchlist, eqats streams `equity_live_stock_info` every 500 ms.
3. Every minute, eqats pulls `fno_live_option_chain` for NIFTY expiry to compute IV‑rank.
4. End‑of‑day, eqats runs `equity_eod_bhavcopy_delivery` to update delivery‑based risk limits.
5. Throughout the day, `fii_dii_activity` informs exposure limits.

By integrating NseKit-MCP as a dedicated data engine, eqats gains reliable, NSE‑compliant market data while keeping the signal, execution, and risk layers focused on their core logic.