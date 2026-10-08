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


# ---------------------------------------------------
# NIFTY 50 YTD 2026 Heatmap
# Baseline: close on 2025-12-31 (last trading day of 2025)
# Sorted: top gainers top-left → top losers bottom-right
# Data source: OpenAlgo Historify local DuckDB (source='db')
# ---------------------------------------------------

import os

import pandas as pd
import plotly.express as px
from openalgo import api

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host="http://127.0.0.1:5000",
)

SYMBOLS = [
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

BASELINE_DATE = pd.Timestamp("2025-12-31").date()

rows = []
last_date_str = None
for sym in SYMBOLS:
    try:
        df = client.history(
            symbol=sym,
            exchange="NSE",
            interval="D",
            start_date="2025-12-30",
            end_date="2026-12-31",
            source="db",
        )
    except Exception as e:
        print(f"{sym}: fetch error: {e}")
        continue

    if not isinstance(df, pd.DataFrame) or df.empty:
        print(f"{sym}: no rows")
        continue

    df = df.sort_index()
    df.index = pd.to_datetime(df.index).date

    if BASELINE_DATE not in df.index:
        print(f"{sym}: missing {BASELINE_DATE}")
        continue

    base = float(df.loc[BASELINE_DATE, "close"])
    last_close = float(df.iloc[-1]["close"])
    last_date_str = df.index[-1].isoformat()

    pct = ((last_close / base) - 1.0) * 100.0
    rows.append({"Symbol": sym, "Change": round(pct, 2)})

if not rows:
    raise SystemExit("No data. Run Historify bulk download first.")

df = pd.DataFrame(rows).sort_values("Change", ascending=False).reset_index(drop=True)

cols = 10
df["row"] = df.index // cols
df["col"] = df.index % cols

pivot_values = df.pivot(index="row", columns="col", values="Change")
pivot_labels = df.pivot(index="row", columns="col", values="Symbol")

fig = px.imshow(pivot_values, color_continuous_scale="RdYlGn", aspect="auto")
fig.update_traces(
    text=pivot_labels.values,
    texttemplate="%{text}<br>%{z:.2f}%",
    hovertemplate="Symbol: %{text}<br>YTD: %{z:.2f}%",
)
fig.update_layout(
    title="NIFTY 50 YTD 2026 Heatmap",
    xaxis={"showticklabels": False, "title": ""},
    yaxis={"showticklabels": False, "autorange": "reversed", "title": ""},
    template="plotly_dark",
    height=600,
)

out = "nifty50_ytd_heatmap.png"
fig.write_image(out, width=1200, height=600, scale=2)
print(f"\nSaved {out}  (as-of {last_date_str}, {len(df)} symbols)")
