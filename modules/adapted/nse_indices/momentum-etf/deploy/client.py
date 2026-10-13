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
Simple client script to test the deployed ETF Momentum Strategy API

Usage:
    python client.py --url https://your-app-url.com --command portfolio
    python client.py --url https://your-app-url.com --command historical --from-date 2024-01-01
"""

import argparse
import json
from typing import Any

import requests


def test_portfolio(api_url: str, amount: float = 1000000, size: int = 5) -> dict[str, Any]:
    """Test portfolio endpoint"""
    url = f"{api_url}/portfolio"
    params = {"amount": amount, "size": size}

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def test_historical(
    api_url: str,
    from_date: str,
    to_date: str = None,
    amount: float = 1000000,
    size: int = 5,
) -> dict[str, Any]:
    """Test historical endpoint"""
    # Use the GET endpoint which works reliably
    url = f"{api_url}/historical"
    params = {"from_date": from_date, "amount": amount, "size": size}
    if to_date:
        params["to_date"] = to_date

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def test_rebalance(
    api_url: str, holdings_file: str = None, from_date: str = None, size: int = 5
) -> dict[str, Any]:
    """Test rebalance endpoint with sample data"""
    url = f"{api_url}/rebalance"

    # Sample holdings data if no file provided
    if not holdings_file:
        data = {
            "holdings": [
                {"symbol": "NIFTYBEES.NS", "units": 350, "price": 120.50},
                {"symbol": "GOLDBEES.NS", "units": 200, "price": -1},
            ],
            "from_date": from_date or "2024-01-01",
            "size": size,
        }
    else:
        # Load holdings from file
        with open(holdings_file) as f:
            holdings_data = json.load(f)

        data = {"holdings": holdings_data, "from_date": from_date, "size": size}

    response = requests.post(url, json=data)
    response.raise_for_status()
    return response.json()


def test_health(api_url: str) -> dict[str, Any]:
    """Test health endpoint"""
    url = f"{api_url}/health"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Test ETF Momentum Strategy API")
    parser.add_argument("--url", required=True, help="API base URL")
    parser.add_argument(
        "--command",
        required=True,
        choices=["portfolio", "historical", "rebalance", "health"],
        help="Command to test",
    )

    # Portfolio options
    parser.add_argument(
        "--amount",
        type=float,
        default=1000000,
        help="Investment amount (default: 1000000)",
    )
    parser.add_argument("--size", type=int, default=5, help="Portfolio size (default: 5)")

    # Historical options
    parser.add_argument("--from-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", help="End date (YYYY-MM-DD)")

    # Rebalance options
    parser.add_argument("--holdings-file", help="Holdings JSON file")

    args = parser.parse_args()

    try:
        print(f"🚀 Testing {args.command} endpoint...")
        print(f"📡 API URL: {args.url}")
        print("-" * 50)

        if args.command == "health":
            result = test_health(args.url)
            print("✅ Health check successful!")
            print(json.dumps(result, indent=2))

        elif args.command == "portfolio":
            result = test_portfolio(args.url, args.amount, args.size)
            print("✅ Portfolio endpoint successful!")
            print(f"💰 Amount: ₹{args.amount:,}")
            print(f"📊 Size: {args.size} ETFs")
            if result.get("status") == "success":
                print("\n📋 Response:")
                print(result["data"]["output"])

        elif args.command == "historical":
            if not args.from_date:
                print("❌ --from-date is required for historical command")
                return

            result = test_historical(args.url, args.from_date, args.to_date, args.amount, args.size)
            print("✅ Historical endpoint successful!")
            print(f"📅 From: {args.from_date}")
            print(f"📅 To: {args.to_date or 'today'}")
            if result.get("status") == "success":
                print("\n📋 Response:")
                print(result["data"]["output"])

        elif args.command == "rebalance":
            result = test_rebalance(args.url, args.holdings_file, args.from_date, args.size)
            print("✅ Rebalance endpoint successful!")
            if args.holdings_file:
                print(f"📁 Holdings file: {args.holdings_file}")
            else:
                print("📁 Using sample holdings data")
            if result.get("status") == "success":
                print("\n📋 Response:")
                print(result["data"]["output"])

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"📋 Error details: {json.dumps(error_detail, indent=2)}")
            except:
                print(f"📋 Error response: {e.response.text}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
