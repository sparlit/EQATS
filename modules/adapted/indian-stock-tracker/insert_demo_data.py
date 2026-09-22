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


import os

with open("/Users/akshay/Desktop/indian_stock_tracker/flask_app.py") as f:
    content = f.read()

insert_code = """

# Demo data for prototype - TODO: Replace with real data sources when available
DEMO_DATA = {
    "indices": [
        {"name": "NIFTY 50", "value": 24847.30, "change": 124.50, "changePct": 0.50},
        {"name": "NIFTY BANK", "value": 52341.20, "change": -89.30, "changePct": -0.17},
        {"name": "NIFTY IT", "value": 36892.10, "change": 234.60, "changePct": 0.64},
        {"name": "SENSEX", "value": 82156.80, "change": -45.20, "changePct": -0.05}
    ],
    "stocks": [
        {"symbol": "RELIANCE", "name": "Reliance Industries", "price": 2847.35, "changePct": 1.50, "sector": "Energy", "recommendation": "Buy"},
        {"symbol": "TCS", "name": "Tata Consultancy Services", "price": 3912.60, "changePct": -0.72, "sector": "IT", "recommendation": "Hold"},
        {"symbol": "HDFCBANK", "name": "HDFC Bank", "price": 1724.80, "changePct": 1.11, "sector": "Banking", "recommendation": "Buy"},
        {"symbol": "INFY", "name": "Infosys", "price": 1847.25, "changePct": -0.79, "sector": "IT", "recommendation": "Hold"},
        {"symbol": "ICICIBANK", "name": "ICICI Bank", "price": 1312.45, "changePct": 1.73, "sector": "Banking", "recommendation": "Buy"},
        {"symbol": "HINDUNILVR", "name": "Hindustan Unilever", "price": 2398.10, "changePct": -1.30, "sector": "FMCG", "recommendation": "Sell"}
    ],
    "sectors": [
        {"name": "Banking", "pct": 1.24}, {"name": "IT", "pct": -0.91},
        {"name": "FMCG", "pct": -0.48}, {"name": "Auto", "pct": 0.34},
        {"name": "Energy", "pct": 1.50}, {"name": "Pharma", "pct": 1.12}
    ],
    "gainers": [
        {"symbol": "BAJFINANCE", "name": "Bajaj Finance", "price": 7248.15, "changePct": 2.21},
        {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "price": 1623.45, "changePct": 2.02},
        {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical", "price": 1682.45, "changePct": 1.75}
    ],
    "losers": [
        {"symbol": "WIPRO", "name": "Wipro", "price": 547.80, "changePct": -1.47},
        {"symbol": "TATAMOTORS", "name": "Tata Motors", "price": 985.40, "changePct": -1.52},
        {"symbol": "BPCL", "name": "Bharat Petroleum", "price": 628.70, "changePct": -1.32}
    ],
    "watchlist": [
        {"symbol": "RELIANCE", "name": "Reliance Industries", "sector": "Energy", "price": 2847.35, "changePct": 1.50},
        {"symbol": "TCS", "name": "Tata Consultancy Services", "sector": "IT", "price": 3912.60, "changePct": -0.72},
        {"symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Banking", "price": 1724.80, "changePct": 1.11},
        {"symbol": "INFY", "name": "Infosys", "sector": "IT", "price": 1847.25, "changePct": -0.79}
    ]
}

@app.context_processor
def inject_demo_data():
    return dict(demo_data=DEMO_DATA)
"""

marker = "init_mutual_funds_db()"
idx = content.find(marker)
if idx >= 0:
    # Find the end of this line and insert after
    end_of_line = content.find("\n", idx)
    # Find the next blank line after init_mutual_funds_db()
    next_line = content.find("\n", end_of_line + 1)
    new_content = content[:next_line] + insert_code + content[next_line:]
    with open("/Users/akshay/Desktop/indian_stock_tracker/flask_app.py", "w") as f:
        f.write(new_content)
    print("Successfully inserted DEMO_DATA and context_processor")
else:
    print("Marker not found")
