from __future__ import annotations

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


"""Free MCP fallback client — tries hosted free MCP servers before yfinance.

Fallback cascade (by merit):
  1. indian-market-mcp  (68 tools, hosted on Render, zero auth)
  2. nse-public-mcp     (12 tools, MySQL-backed, production nginx)
  3. tapetide-mcp       (34 tools, free tier 1K req/day)
  4. yfinance library   (last resort, no MCP server needed)

Each endpoint speaks JSON-RPC 2.0 over Streamable HTTP — same protocol
as NseBseMcpClient, so we reuse the wire format but skip session init
for stateless hosted servers.
"""


import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Hosted free MCP endpoints (merit order) ───────────────────────

FREE_MCP_ENDPOINTS: list[dict[str, Any]] = [
    {
        "name": "nse-public-mcp",
        "url": "https://stockmcp.alokbarnwal.com/mcp",
        "timeout": 20.0,
        "tools_map": {
            "get_quote": "get_stock_quote",
            "get_historical": "get_ohlc_data",
            "get_technical": "get_technical_indicators",
            "get_support_resistance": "get_support_resistance",
        },
    },
    {
        "name": "indian-market-mcp",
        "url": "https://indian-market-mcp-wweh.onrender.com/mcp",
        "timeout": 30.0,
        "tools_map": {
            "get_quote": "get_stock_quote",
            "get_historical": "get_stock_history",
            "get_fundamentals": "get_stock_fundamentals",
            "get_corporate_actions": "get_corporate_actions",
            "get_market_cap": "get_stock_quote",
            "search_symbol": "search_stocks",
        },
    },
    {
        "name": "tapetide-mcp",
        "url": "https://mcp.tapetide.com/mcp",
        "timeout": 20.0,
        "tools_map": {
            "get_quote": "get_stock_quote",
            "get_historical": "get_stock_history",
            "get_fundamentals": "get_stock_fundamentals",
            "get_corporate_actions": "get_corporate_actions",
            "get_market_cap": "get_stock_quote",
            "search_symbol": "search_stocks",
        },
        "auth_required": True,
    },
]


class FreeMcpError(RuntimeError):
    pass


class FreeMcpClient:
    """Try multiple free hosted MCP endpoints with JSON-RPC 2.0.

    Each endpoint requires an initialize handshake (like nse-bse-mcp).
    The client caches session IDs per endpoint for reuse.
    """

    def __init__(
        self,
        endpoints: list[dict[str, Any]] | None = None,
        *,
        max_retries: int = 1,
    ) -> None:
        self.endpoints = endpoints or FREE_MCP_ENDPOINTS
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=30.0)
        self._working_url: str | None = None
        self._working_name: str | None = None
        self._session_ids: dict[str, str] = {}
        self._initialized: dict[str, bool] = {}
        self._rate_limited: dict[str, float] = {}  # url -> timestamp when OK to retry
        self._next_id = 1

    def _post_jsonrpc(self, url: str, payload: dict, timeout: float) -> dict | None:
        """Send a JSON-RPC 2.0 POST and return the parsed result."""
        # Skip if rate-limited (retry after 60s)
        if url in self._rate_limited:
            if time.time() < self._rate_limited[url]:
                return None
            del self._rate_limited[url]

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # Add session ID if we have one for this URL
        session_id = self._session_ids.get(url)
        if session_id:
            headers["mcp-session-id"] = session_id

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._http.post(url, json=payload, headers=headers, timeout=timeout)
                # Capture session ID from response
                new_session = resp.headers.get("mcp-session-id")
                if new_session:
                    self._session_ids[url] = new_session
                # Handle rate limiting
                if resp.status_code == 429:
                    self._rate_limited[url] = time.time() + 60
                    logger.debug(f"MCP rate limited at {url}, backing off 60s")
                    return None
                if resp.status_code >= 500:
                    continue
                if not resp.text.strip():
                    return None
                # Handle SSE-framed responses
                text = resp.text.strip()
                if text.startswith("data:") or "\ndata:" in text or "event:" in text:
                    for line in reversed(text.splitlines()):
                        if line.startswith("data:"):
                            import json

                            body = json.loads(line.removeprefix("data:").strip())
                            if "error" in body:
                                # Check for rate limit in error text
                                err_msg = str(body.get("error", ""))
                                if "rate" in err_msg.lower() or "too many" in err_msg.lower():
                                    self._rate_limited[url] = time.time() + 60
                                return None
                            return body.get("result", {})
                    return None
                import json

                body = json.loads(text)
                if "error" in body:
                    err_msg = str(body.get("error", ""))
                    if "rate" in err_msg.lower() or "too many" in err_msg.lower():
                        self._rate_limited[url] = time.time() + 60
                    logger.debug(f"MCP error at {url}: {body['error']}")
                    return None
                return body.get("result", {})
            except Exception as exc:
                logger.debug(f"MCP attempt {attempt} failed at {url}: {exc}")
                if attempt == self.max_retries:
                    return None
        return None

    def _ensure_initialized(self, url: str, timeout: float) -> bool:
        """Send initialize + notifications/initialized handshake."""
        if self._initialized.get(url):
            return True

        rid = self._next_id
        self._next_id += 1

        # Step 1: initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "indian-quant-free", "version": "0.1.0"},
            },
        }
        result = self._post_jsonrpc(url, init_payload, timeout)
        if result is None:
            return False

        # Step 2: notifications/initialized
        notif_payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._post_jsonrpc(url, notif_payload, timeout)

        self._initialized[url] = True
        return True

    def _call_tool_http(self, endpoint: dict, tool_name: str, arguments: dict) -> Any:
        """Call a tool on a specific hosted MCP endpoint."""
        url = endpoint["url"]
        timeout = endpoint.get("timeout", 20.0)

        # Ensure session is initialized
        if not self._ensure_initialized(url, timeout):
            return None

        rid = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        result = self._post_jsonrpc(url, payload, timeout)
        if result is None:
            return None

        if result.get("isError"):
            return None

        # Extract text/structured content
        structured = result.get("structuredContent")
        if structured is not None:
            return structured

        for item in result.get("content", []):
            if item.get("type") == "text":
                text = item.get("text", "")
                try:
                    import json

                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
        return None

    def call_tool(self, tool_type: str, arguments: dict) -> Any:
        """Try tool_type across all free MCP endpoints (merit order).

        tool_type is our internal name: 'get_quote', 'get_historical', etc.
        Each endpoint maps it to their own tool name.
        """
        # If we already know a working endpoint, try it first
        if self._working_url and self._working_name:
            for ep in self.endpoints:
                if ep["url"] == self._working_url:
                    mapped = ep.get("tools_map", {}).get(tool_type)
                    if mapped:
                        result = self._call_tool_http(ep, mapped, arguments)
                        if result is not None:
                            return result
                    break
            # Previous working endpoint failed, reset
            self._working_url = None
            self._working_name = None

        # Try all endpoints in merit order
        for ep in self.endpoints:
            # Skip endpoints that require auth (no token available)
            if ep.get("auth_required"):
                continue
            mapped = ep.get("tools_map", {}).get(tool_type)
            if not mapped:
                continue

            result = self._call_tool_http(ep, mapped, arguments)
            if result is not None:
                self._working_url = ep["url"]
                self._working_name = ep["name"]
                logger.info(f"Free MCP fallback succeeded: {ep['name']}")
                return result

        return None

    def health_check(self) -> dict[str, bool]:
        """Check which free MCP endpoints are reachable (via initialize)."""
        results = {}
        for ep in self.endpoints:
            try:
                url = ep["url"]
                timeout = ep.get("timeout", 10.0)
                results[ep["name"]] = self._ensure_initialized(url, timeout)
            except Exception:
                results[ep["name"]] = False
        return results

    def close(self) -> None:
        self._http.close()
