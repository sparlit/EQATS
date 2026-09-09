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
Test cleaned tool serialization
"""

import json

import requests


def test_clean_tools():
    """Test that tools are now properly serialized"""
    print("🔍 Testing Cleaned Tool Serialization")
    print("=" * 45)

    try:
        # Test tools/list with cleaned serialization
        response = requests.post(
            "http://localhost:8000/jsonrpc", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1}, timeout=5
        )

        if response.status_code == 200:
            result = response.json()
            if "result" in result:
                tools = result["result"]["tools"]
                print(f"Found {len(tools)} tools")

                if len(tools) > 0:
                    first_tool = tools[0]
                    print("\n📋 First tool structure:")
                    print(json.dumps(first_tool, indent=2))

                    # Check for clean fields
                    expected_fields = {"name", "description", "inputSchema"}
                    actual_fields = set(first_tool.keys())

                    if actual_fields == expected_fields:
                        print("\nTool serialization is clean!")
                        print(f"   Fields: {sorted(actual_fields)}")
                    else:
                        extra_fields = actual_fields - expected_fields
                        missing_fields = expected_fields - actual_fields
                        if extra_fields:
                            print(f"\n⚠️  Extra fields: {extra_fields}")
                        if missing_fields:
                            print(f"\nMissing fields: {missing_fields}")
                else:
                    print("No tools found")
            else:
                print(f"Error in response: {result}")
        else:
            print(f"HTTP Error: {response.status_code}")

    except Exception as e:
        print(f"Connection error: {e}")
        print("Make sure server is running: python ise_mcp_server.py")


if __name__ == "__main__":
    test_clean_tools()
