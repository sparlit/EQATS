import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


#!/usr/bin/env python3
"""
Indian Stock Exchange MCP Server - Stdio Transport

This server provides access to live market data from Indian Stock Exchanges (BSE & NSE)
through the Model Context Protocol (MCP) using stdio transport.
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import httpx
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import EmbeddedResource, ImageContent, LoggingLevel, Resource, TextContent, Tool

from .config import Config

# Configure logging for stdio (to stderr)
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # Log to stderr to avoid interfering with stdio MCP communication
)
logger = logging.getLogger("ise-mcp-stdio")

# Create MCP server instance
app = Server("indian-stock-exchange")


class ISEClient:
    """Client for Indian Stock Exchange API"""

    def __init__(self, base_url: str = Config.BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=Config.REQUEST_TIMEOUT, headers=Config.get_headers())

    async def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make HTTP request to the API with x-api-key header"""
        try:
            url = f"{self.base_url}{endpoint}"
            if params:
                from urllib.parse import urlencode

                url += f"?{urlencode(params)}"

            # Prepare headers with x-api-key
            headers = Config.get_headers().copy()
            if Config.API_KEY:
                headers["x-api-key"] = Config.API_KEY

            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.exception(f"HTTP error occurred: {e}")
            msg = f"API request failed: {e!s}"
            raise Exception(msg)
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            msg = f"Unexpected error: {e!s}"
            raise Exception(msg)

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Global client instance
ise_client = ISEClient()


@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for Indian Stock Exchange data"""
    return [
        Tool(
            name="get_stock_data",
            description="Get detailed financial data for a specific company by name",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Company name, shortened name, or search term"}
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="search_industry",
            description="Search for companies within a specific industry",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Industry search term"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="search_mutual_funds",
            description="Search for mutual funds",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Mutual fund search term"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="get_trending_stocks",
            description="Get trending stocks with top gainers and losers",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_52_week_high_low",
            description="Get stocks with highest and lowest prices in the last 52 weeks",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_nse_most_active",
            description="Get most active stocks on NSE by trading volume",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_bse_most_active",
            description="Get most active stocks on BSE by trading volume",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_mutual_funds",
            description="Get latest mutual fund data with NAV and returns",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_price_shockers",
            description="Get stocks with significant price changes",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_commodities",
            description="Get real-time commodity futures data",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_analyst_recommendations",
            description="Get analyst target prices and recommendations for a stock",
            inputSchema={
                "type": "object",
                "properties": {"stock_id": {"type": "string", "description": "Stock identifier"}},
                "required": ["stock_id"],
            },
        ),
        Tool(
            name="get_stock_forecasts",
            description="Get detailed forecast information for a stock",
            inputSchema={
                "type": "object",
                "properties": {
                    "stock_id": {"type": "string", "description": "Stock identifier"},
                    "measure_code": {
                        "type": "string",
                        "enum": [
                            "EPS",
                            "CPS",
                            "CPX",
                            "DPS",
                            "EBI",
                            "EBT",
                            "GPS",
                            "GRM",
                            "NAV",
                            "NDT",
                            "NET",
                            "PRE",
                            "ROA",
                            "ROE",
                            "SAL",
                        ],
                        "description": "Measure code for forecast",
                    },
                    "period_type": {"type": "string", "enum": ["Annual", "Interim"], "description": "Period type"},
                    "data_type": {"type": "string", "enum": ["Actuals", "Estimates"], "description": "Data type"},
                    "age": {
                        "type": "string",
                        "enum": ["OneWeekAgo", "ThirtyDaysAgo", "SixtyDaysAgo", "NinetyDaysAgo", "Current"],
                        "description": "Data age",
                    },
                },
                "required": ["stock_id", "measure_code", "period_type", "data_type", "age"],
            },
        ),
        Tool(
            name="get_historical_data",
            description="Get historical stock data with various filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "stock_name": {"type": "string", "description": "Stock symbol or name"},
                    "period": {
                        "type": "string",
                        "enum": ["1m", "6m", "1yr", "3yr", "5yr", "10yr", "max"],
                        "description": "Time period",
                        "default": "5yr",
                    },
                    "filter": {
                        "type": "string",
                        "enum": ["default", "price", "pe", "sm", "evebitda", "ptb", "mcs"],
                        "description": "Data filter",
                        "default": "default",
                    },
                },
                "required": ["stock_name"],
            },
        ),
        Tool(
            name="get_historical_stats",
            description="Get historical statistics for a stock",
            inputSchema={
                "type": "object",
                "properties": {
                    "stock_name": {"type": "string", "description": "Stock symbol or name"},
                    "stats": {
                        "type": "string",
                        "enum": [
                            "quarter_results",
                            "yoy_results",
                            "balancesheet",
                            "cashflow",
                            "ratios",
                            "shareholding_pattern_quarterly",
                            "shareholding_pattern_yearly",
                        ],
                        "description": "Type of historical statistics",
                    },
                },
                "required": ["stock_name", "stats"],
            },
        ),
    ]


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls for Indian Stock Exchange data"""
    try:
        if name == "get_stock_data":
            data = await ise_client._make_request("/stock", {"name": arguments["name"]})
            return [
                types.TextContent(
                    type="text",
                    text=f"Stock Data for {arguments['name']}:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        if name == "search_industry":
            data = await ise_client._make_request("/industry_search", {"query": arguments["query"]})
            return [
                types.TextContent(
                    type="text",
                    text=f"Industry Search Results for '{arguments['query']}':\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        if name == "search_mutual_funds":
            data = await ise_client._make_request("/mutual_fund_search", {"query": arguments["query"]})
            return [
                types.TextContent(
                    type="text",
                    text=f"Mutual Fund Search Results for '{arguments['query']}':\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        if name == "get_trending_stocks":
            data = await ise_client._make_request("/trending")
            return [
                types.TextContent(
                    type="text", text=f"Trending Stocks:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_52_week_high_low":
            data = await ise_client._make_request("/fetch_52_week_high_low_data")
            return [
                types.TextContent(
                    type="text", text=f"52 Week High/Low Data:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_nse_most_active":
            data = await ise_client._make_request("/NSE_most_active")
            return [
                types.TextContent(
                    type="text", text=f"NSE Most Active Stocks:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_bse_most_active":
            data = await ise_client._make_request("/BSE_most_active")
            return [
                types.TextContent(
                    type="text", text=f"BSE Most Active Stocks:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_mutual_funds":
            data = await ise_client._make_request("/mutual_funds")
            return [
                types.TextContent(
                    type="text", text=f"Mutual Funds Data:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_price_shockers":
            data = await ise_client._make_request("/price_shockers")
            return [
                types.TextContent(
                    type="text", text=f"Price Shockers:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_commodities":
            data = await ise_client._make_request("/commodities")
            return [
                types.TextContent(
                    type="text", text=f"Commodity Futures Data:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}"
                )
            ]

        if name == "get_analyst_recommendations":
            data = await ise_client._make_request("/stock_target_price", {"stock_id": arguments["stock_id"]})
            return [
                types.TextContent(
                    type="text",
                    text=f"Analyst Recommendations for {arguments['stock_id']}:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        if name == "get_stock_forecasts":
            params = {
                "stock_id": arguments["stock_id"],
                "measure_code": arguments["measure_code"],
                "period_type": arguments["period_type"],
                "data_type": arguments["data_type"],
                "age": arguments["age"],
            }
            data = await ise_client._make_request("/stock_forecasts", params)
            return [
                types.TextContent(
                    type="text",
                    text=f"Stock Forecasts for {arguments['stock_id']}:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        if name == "get_historical_data":
            params = {"stock_name": arguments["stock_name"]}
            if "period" in arguments:
                params["period"] = arguments["period"]
            if "filter" in arguments:
                params["filter"] = arguments["filter"]

            data = await ise_client._make_request("/historical_data", params)
            return [
                types.TextContent(
                    type="text",
                    text=f"Historical Data for {arguments['stock_name']}:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        if name == "get_historical_stats":
            params = {"stock_name": arguments["stock_name"], "stats": arguments["stats"]}
            data = await ise_client._make_request("/historical_stats", params)
            return [
                types.TextContent(
                    type="text",
                    text=f"Historical Stats ({arguments['stats']}) for {arguments['stock_name']}:\n\n{json.dumps(data, indent=2, ensure_ascii=False)}",
                )
            ]

        msg = f"Unknown tool: {name}"
        raise ValueError(msg)

    except Exception as e:
        logger.exception(f"Error in tool {name}: {e!s}")
        return [types.TextContent(type="text", text=f"Error executing {name}: {e!s}")]


async def main():
    """Main entry point for the stdio server"""
    try:
        # Validate configuration
        Config.validate_config()
        logger.info("Configuration validated successfully")
        logger.info("ISE MCP Stdio Server starting...")
        logger.info(f"API Base URL: {Config.BASE_URL}")

        # Run the stdio server
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    except ValueError as e:
        logger.exception(f"Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception(f"Server error: {e}")
        sys.exit(1)
    finally:
        await ise_client.close()


if __name__ == "__main__":
    asyncio.run(main())
