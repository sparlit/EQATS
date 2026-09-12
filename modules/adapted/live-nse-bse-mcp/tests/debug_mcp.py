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
Debug script to test MCP protocol flow like Cursor would
"""

import json

import requests


def test_mcp_flow():
    """Test the exact MCP flow that Cursor uses"""
    base_url = "http://localhost:8000/jsonrpc"

    print("🔍 Testing MCP Protocol Flow")
    print("=" * 40)

    # 1. Initialize
    print("\n1. Testing initialize...")
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cursor-debug", "version": "1.0.0"},
        },
        "id": 1,
    }

    try:
        response = requests.post(base_url, json=init_request, timeout=5)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Response: {json.dumps(result, indent=2)}")

            # Check if initialize was successful
            if "result" in result:
                capabilities = result["result"].get("capabilities", {})
                print(f"Server capabilities: {capabilities}")
                has_tools = "tools" in capabilities
                print(f"Tools supported: {has_tools}")
        else:
            print(f"HTTP Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

    # 2. List tools
    print("\n2. Testing tools/list...")
    tools_request = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}

    try:
        response = requests.post(base_url, json=tools_request, timeout=5)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Response keys: {result.keys()}")
            if "result" in result:
                tools = result["result"].get("tools", [])
                print(f"Tools count: {len(tools)}")
                if len(tools) > 0:
                    print(f"First tool: {tools[0]['name']}")
                    print(f"Tool structure: {list(tools[0].keys())}")
            else:
                print(f"Error: {result}")
        else:
            print(f"HTTP Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

    # 3. Test a simple tool call
    print("\n3. Testing tools/call...")
    call_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_trending_stocks", "arguments": {}},
        "id": 3,
    }

    try:
        response = requests.post(base_url, json=call_request, timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            if "result" in result:
                print("Tool call successful")
                content = result["result"].get("content", [])
                print(f"Content items: {len(content)}")
            else:
                print(f"Tool call failed: {result}")
        else:
            print(f"HTTP Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_mcp_flow()
