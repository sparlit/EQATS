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
Generic Python MCP Client

A comprehensive MCP client that can connect to any MCP server (stdio or HTTP)
using the official Python MCP SDK.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
from mcp import Client
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.types import (
    AnyRequest,
    CallToolRequest,
    CallToolResult,
    GetPromptRequest,
    GetPromptResult,
    InitializeRequest,
    InitializeResult,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsRequest,
    ListToolsResult,
    ReadResourceRequest,
    ReadResourceResult,
    Tool,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-client")


@dataclass
class MCPServerConfig:
    """Configuration for MCP server connection"""

    name: str
    transport_type: str  # "stdio" or "http"
    # For stdio
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    # For HTTP
    url: str | None = None
    headers: dict[str, str] | None = None


class HTTPTransport:
    """HTTP transport for MCP client"""

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self.url = url
        self.headers = headers or {}
        self.client = httpx.AsyncClient(timeout=30.0)
        self._request_id = 0

    def _next_id(self) -> int:
        """Get next request ID"""
        self._request_id += 1
        return self._request_id

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send JSON-RPC request over HTTP"""
        request_data = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": self._next_id()}

        logger.debug(f"Sending request: {method}")

        try:
            response = await self.client.post(
                self.url, json=request_data, headers={"Content-Type": "application/json", **self.headers}
            )
            response.raise_for_status()
            result = response.json()

            if "error" in result:
                msg = f"MCP Error: {result['error']}"
                raise Exception(msg)

            return result.get("result", {})

        except httpx.HTTPError as e:
            logger.exception(f"HTTP error: {e}")
            msg = f"HTTP request failed: {e!s}"
            raise Exception(msg)

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


class MCPClient:
    """Generic MCP client supporting both stdio and HTTP transports"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.session: ClientSession | None = None
        self.http_transport: HTTPTransport | None = None
        self.tools: list[Tool] = []
        self.server_info: dict[str, Any] = {}

    async def connect(self) -> bool:
        """Connect to MCP server"""
        try:
            if self.config.transport_type == "stdio":
                return await self._connect_stdio()
            if self.config.transport_type == "http":
                return await self._connect_http()
            msg = f"Unsupported transport type: {self.config.transport_type}"
            raise ValueError(msg)
        except Exception as e:
            logger.exception(f"Failed to connect to {self.config.name}: {e}")
            return False

    async def _connect_stdio(self) -> bool:
        """Connect using stdio transport"""
        if not self.config.command:
            msg = "Command required for stdio transport"
            raise ValueError(msg)

        # Create stdio client session
        async with stdio_client(
            command=self.config.command, args=self.config.args or [], env=self.config.env or {}
        ) as (read, write):
            self.session = ClientSession(read, write)

            # Initialize
            await self._initialize()

            # Load tools
            await self._load_tools()

            return True

    async def _connect_http(self) -> bool:
        """Connect using HTTP transport"""
        if not self.config.url:
            msg = "URL required for HTTP transport"
            raise ValueError(msg)

        self.http_transport = HTTPTransport(url=self.config.url, headers=self.config.headers)

        # Initialize
        await self._initialize()

        # Load tools
        await self._load_tools()

        return True

    async def _initialize(self):
        """Initialize MCP session"""
        if self.session:
            # Stdio initialization
            result = await self.session.initialize()
            self.server_info = result.serverInfo.model_dump() if result.serverInfo else {}
        elif self.http_transport:
            # HTTP initialization
            init_params = {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "python-mcp-client", "version": "1.0.0"},
            }
            result = await self.http_transport.send_request("initialize", init_params)
            self.server_info = result.get("serverInfo", {})

        logger.info(
            f"Connected to {self.server_info.get('name', 'Unknown')} v{self.server_info.get('version', 'Unknown')}"
        )

    async def _load_tools(self):
        """Load available tools from server"""
        if self.session:
            # Stdio tools loading
            result = await self.session.list_tools()
            self.tools = result.tools
        elif self.http_transport:
            # HTTP tools loading
            result = await self.http_transport.send_request("tools/list")
            tools_data = result.get("tools", [])
            # Convert dict tools to Tool objects
            self.tools = []
            for tool_data in tools_data:
                tool = Tool(
                    name=tool_data["name"], description=tool_data["description"], inputSchema=tool_data["inputSchema"]
                )
                self.tools.append(tool)

        logger.info(f"Loaded {len(self.tools)} tools")

    async def list_tools(self) -> list[Tool]:
        """Get list of available tools"""
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a specific tool"""
        arguments = arguments or {}

        if self.session:
            # Stdio tool call
            result = await self.session.call_tool(name, arguments)
            return result.content
        if self.http_transport:
            # HTTP tool call
            params = {"name": name, "arguments": arguments}
            result = await self.http_transport.send_request("tools/call", params)
            return result.get("content", [])
        msg = "Not connected to any server"
        raise Exception(msg)

    async def get_tool_by_name(self, name: str) -> Tool | None:
        """Get tool by name"""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    async def list_prompts(self) -> list[Any]:
        """List available prompts (if supported)"""
        if self.session:
            try:
                result = await self.session.list_prompts()
                return result.prompts
            except Exception:
                return []
        elif self.http_transport:
            try:
                result = await self.http_transport.send_request("prompts/list")
                return result.get("prompts", [])
            except Exception:
                return []
        return []

    async def list_resources(self) -> list[Any]:
        """List available resources (if supported)"""
        if self.session:
            try:
                result = await self.session.list_resources()
                return result.resources
            except Exception:
                return []
        elif self.http_transport:
            try:
                result = await self.http_transport.send_request("resources/list")
                return result.get("resources", [])
            except Exception:
                return []
        return []

    def get_server_info(self) -> dict[str, Any]:
        """Get server information"""
        return self.server_info

    async def close(self):
        """Close connection"""
        if self.http_transport:
            await self.http_transport.close()
        # Session cleanup is handled by context manager for stdio


class MCPClientManager:
    """Manager for multiple MCP clients"""

    def __init__(self):
        self.clients: dict[str, MCPClient] = {}

    async def add_client(self, config: MCPServerConfig) -> bool:
        """Add and connect to an MCP server"""
        client = MCPClient(config)
        success = await client.connect()

        if success:
            self.clients[config.name] = client
            logger.info(f"Successfully connected to {config.name}")
            return True
        logger.error(f"Failed to connect to {config.name}")
        return False

    def get_client(self, name: str) -> MCPClient | None:
        """Get client by name"""
        return self.clients.get(name)

    async def list_all_tools(self) -> dict[str, list[Tool]]:
        """List tools from all connected servers"""
        all_tools = {}
        for name, client in self.clients.items():
            all_tools[name] = await client.list_tools()
        return all_tools

    async def call_tool_on_server(
        self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        """Call a tool on a specific server"""
        client = self.clients.get(server_name)
        if not client:
            msg = f"Server {server_name} not found"
            raise Exception(msg)

        return await client.call_tool(tool_name, arguments)

    async def close_all(self):
        """Close all client connections"""
        for client in self.clients.values():
            await client.close()
        self.clients.clear()


# Convenience functions for common use cases


async def create_http_client(url: str, headers: dict[str, str] | None = None) -> MCPClient:
    """Create HTTP MCP client"""
    config = MCPServerConfig(name="http-server", transport_type="http", url=url, headers=headers)

    client = MCPClient(config)
    await client.connect()
    return client


async def create_stdio_client(
    command: str, args: list[str] | None = None, env: dict[str, str] | None = None
) -> MCPClient:
    """Create stdio MCP client"""
    config = MCPServerConfig(name="stdio-server", transport_type="stdio", command=command, args=args, env=env)

    client = MCPClient(config)
    await client.connect()
    return client


# Example usage and demo functions


async def demo_http_client(url: str = "http://localhost:8000/jsonrpc"):
    """Demo HTTP MCP client with Indian Stock Exchange server"""
    print("Connecting to Indian Stock Exchange MCP Server...")
    print("=" * 50)

    try:
        # Create HTTP client
        client = await create_http_client(url)

        # Get server info
        info = client.get_server_info()
        print(f"Connected to: {info.get('name', 'Unknown')} v{info.get('version', 'Unknown')}")

        # List tools
        tools = await client.list_tools()
        print(f"🔧 Available tools: {len(tools)}")
        for i, tool in enumerate(tools[:5], 1):
            print(f"   {i}. {tool.name} - {tool.description}")
        if len(tools) > 5:
            print(f"   ... and {len(tools) - 5} more tools")

        # Demo tool calls
        print("\n📈 Demo Tool Calls:")

        # Get trending stocks
        print("   1. Getting trending stocks...")
        result = await client.call_tool("get_trending_stocks")
        if result:
            print("      Success! (Data received)")

        # Search for a stock
        print("   2. Searching for Reliance stock...")
        result = await client.call_tool("get_stock_data", {"name": "Reliance"})
        if result:
            print("      Success! (Stock data received)")

        # Get NSE most active
        print("   3. Getting NSE most active stocks...")
        result = await client.call_tool("get_nse_most_active")
        if result:
            print("      Success! (NSE data received)")

        print("\n🎉 Demo completed successfully!")

        # Close connection
        await client.close()

    except Exception as e:
        print(f"Demo failed: {e}")


if __name__ == "__main__":
    # Run demo
    asyncio.run(demo_http_client())
