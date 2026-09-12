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
Check tool serialization to debug Cursor issue
"""

import asyncio
import json

from mcp.types import Tool


# Replicate the tool creation from the server
def create_test_tool():
    return Tool(
        name="get_stock_data",
        description="Get detailed financial data for a specific company by name",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Company name, shortened name, or search term"}},
            "required": ["name"],
        },
    )


def test_serialization():
    print("🔍 Testing Tool Serialization")
    print("=" * 40)

    tool = create_test_tool()

    print("1. Tool object attributes:")
    print(f"   - name: {tool.name}")
    print(f"   - description: {tool.description}")
    print(f"   - inputSchema: {tool.inputSchema}")

    print("\n2. model_dump() output:")
    dumped = tool.model_dump()
    print(json.dumps(dumped, indent=2))

    print(f"\n3. Keys in dumped tool: {list(dumped.keys())}")

    print("\n4. Expected MCP tool format should only have:")
    print("   - name")
    print("   - description")
    print("   - inputSchema")

    # Check for extra fields
    expected_fields = {"name", "description", "inputSchema"}
    actual_fields = set(dumped.keys())
    extra_fields = actual_fields - expected_fields

    if extra_fields:
        print(f"\nExtra fields found: {extra_fields}")
        print("   These might be confusing Cursor!")
    else:
        print("\nTool serialization looks correct")


if __name__ == "__main__":
    test_serialization()
