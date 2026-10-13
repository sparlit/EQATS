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


"""MCP client for nse-bse-mcp over Streamable HTTP transport.

Speaks JSON-RPC 2.0 against the server's ``/mcp`` endpoint, handling both
plain-JSON and SSE-framed responses. The client is deliberately thin: it
returns parsed tool payloads; contract mapping happens in ingestion modules.
"""


import json
import uuid
from typing import Any

import httpx

MCP_PROTOCOL_VERSION = "2025-03-26"


class McpError(RuntimeError):
    pass


class NseBseMcpClient:
    def __init__(
        self,
        base_url: str = "http://localhost:3000/mcp",
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
        client_name: str = "indian-quant",
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.client_name = client_name
        self._http = http_client or httpx.Client(timeout=timeout)
        self._owns_http = http_client is None
        self._session_id: str | None = None
        self._next_id = 1
        self._initialized = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _next_request_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    @staticmethod
    def _parse_response_body(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            raise McpError("empty MCP response body")
        if stripped.startswith("data:") or "\ndata:" in stripped or "event:" in stripped:
            for line in reversed(stripped.splitlines()):
                if line.startswith("data:"):
                    return json.loads(line.removeprefix("data:").strip())
            raise McpError(f"no data frame in SSE response: {stripped[:200]}")
        return json.loads(stripped)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._http.post(
                    self.base_url,
                    json=payload,
                    headers=self._headers(),
                )
                session = resp.headers.get("mcp-session-id")
                if session:
                    self._session_id = session
                resp.raise_for_status()
                if not resp.text.strip():
                    return {}
                body = self._parse_response_body(resp.text)
                if "error" in body:
                    raise McpError(f"MCP error: {body['error']}")
                return body
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
        raise McpError(f"MCP request failed after {self.max_retries} attempts: {last_error}")

    def initialize(self) -> dict[str, Any]:
        body = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": self.client_name, "version": "0.1.0"},
                },
            }
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        return body.get("result", {})

    def ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def list_tools(self) -> list[dict[str, Any]]:
        self.ensure_initialized()
        body = self._post({"jsonrpc": "2.0", "id": self._next_request_id(), "method": "tools/list"})
        return body.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool and return its first structured/text payload."""
        self.ensure_initialized()
        body = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        result = body.get("result", {})
        if result.get("isError"):
            content = result.get("content", [])
            detail = content[0].get("text") if content else "unknown error"
            raise McpError(f"tool {name} failed: {detail}")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        for item in result.get("content", []):
            if item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
        self._session_id = None
        self._initialized = False


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
