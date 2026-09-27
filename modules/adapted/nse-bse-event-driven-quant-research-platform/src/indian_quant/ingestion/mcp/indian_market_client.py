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


"""Indian Market MCP client via direct Python API.

Calls Indian Market MCP tool functions directly (no subprocess overhead).
68 tools: stocks, derivatives, indices, mutual funds, ETFs, commodities,
currency, IPOs, bonds, market data, technicals, screener, news, financials,
candlestick patterns, shareholding, MF analysis.
"""


import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class IndianMarketError(RuntimeError):
    pass


class IndianMarketClient:
    def __init__(self) -> None:
        from indian_market_mcp.server import mcp

        self._tools = mcp._tool_manager._tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._tools:
            msg = f"unknown tool: {name}"
            raise IndianMarketError(msg)
        try:
            result = self._tools[name].fn(**(arguments or {}))
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return result
            return result
        except Exception as exc:
            msg = f"tool {name} failed: {exc}"
            raise IndianMarketError(msg) from exc

    def close(self) -> None:
        pass


def get_market_cap(symbol: str) -> float | None:
    try:
        client = IndianMarketClient()
        result = client.call_tool("get_company_profile", {"symbol": symbol})
        return result.get("market_cap")
    except Exception:
        return None


def get_shareholding(symbol: str) -> dict[str, Any] | None:
    try:
        client = IndianMarketClient()
        return client.call_tool("get_shareholding_pattern", {"symbol": symbol})
    except Exception:
        return None
