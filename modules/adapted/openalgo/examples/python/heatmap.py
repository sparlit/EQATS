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

import pandas as pd
import plotly.express as px
from openalgo import api

# ---------------------------------------------------
# OpenAlgo Client
# ---------------------------------------------------
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host="http://127.0.0.1:5000",
)

print("OpenAlgo Python Bot is running.")

# ---------------------------------------------------
# NIFTY 50 SYMBOLS
# ---------------------------------------------------
symbols = [
    "INDIGO",
    "TRENT",
    "HINDUNILVR",
    "HCLTECH",
    "WIPRO",
    "INFY",
    "TATACONSUM",
    "TATASTEEL",
    "ITC",
    "ASIANPAINT",
    "SBILIFE",
    "LT",
    "SHRIRAMFIN",
    "BEL",
    "SBIN",
    "COALINDIA",
    "KOTAKBANK",
    "TCS",
    "SUNPHARMA",
    "MAXHEALTH",
    "NESTLEIND",
    "RELIANCE",
    "ETERNAL",
    "APOLLOHOSP",
    "ICICIBANK",
    "GRASIM",
    "ULTRACEMCO",
    "ADANIENT",
    "AXISBANK",
    "DRREDDY",
    "TECHM",
    "TMPV",
    "JIOFIN",
    "NTPC",
    "BAJFINANCE",
    "BHARTIARTL",
    "POWERGRID",
    "HINDALCO",
    "HDFCBANK",
    "TITAN",
    "HDFCLIFE",
    "MARUTI",
    "BAJAJFINSV",
    "ADANIPORTS",
    "CIPLA",
    "JSWSTEEL",
    "BAJAJ-AUTO",
    "ONGC",
    "EICHERMOT",
    "M&M",
]

# ---------------------------------------------------
# FETCH LIVE QUOTES
# ---------------------------------------------------
quote_symbols = [{"symbol": s, "exchange": "NSE"} for s in symbols]
response = client.multiquotes(symbols=quote_symbols)

rows = []

print("\n Live Market Data:")
for item in response["results"]:
    symbol = item["symbol"]
    ltp = item["data"]["ltp"]
    prev_close = item["data"]["prev_close"]

    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)

    # Print immediately (rule)
    print(f"{symbol} | LTP: {ltp} | Change: {change_pct}%")

    rows.append([symbol, change_pct])

# ---------------------------------------------------
# PREPARE + SORT DATA
# ---------------------------------------------------
df = pd.DataFrame(rows, columns=["Symbol", "Change"])

# SORT: TOP GAINERS → BOTTOM LOSERS
df = df.sort_values("Change", ascending=False).reset_index(drop=True)

# Grid: 10 columns x 5 rows
cols = 10
df["row"] = df.index // cols
df["col"] = df.index % cols

pivot_values = df.pivot(index="row", columns="col", values="Change")
pivot_labels = df.pivot(index="row", columns="col", values="Symbol")

# ---------------------------------------------------
# HEATMAP PLOT
# ---------------------------------------------------
fig = px.imshow(pivot_values, color_continuous_scale="RdYlGn", aspect="auto")

fig.update_traces(
    text=pivot_labels.values,
    texttemplate="%{text}<br>%{z:.2f}%",
    hovertemplate="Symbol: %{text}<br>Change: %{z:.2f}%",
)

fig.update_layout(
    title="NIFTY 50 Sorted Heatmap (%)",
    xaxis={"type": "category", "title": ""},
    yaxis={"type": "category", "autorange": "reversed", "title": ""},
    template="plotly_dark",
    height=600,
)

# ---------------------------------------------------
# SAVE IMAGE (NO HTML OUTPUT)
# ---------------------------------------------------
fig.write_image("nifty50_heatmap.png", width=1200, height=600, scale=2)

print("\n Heatmap saved as nifty50_heatmap.png")
