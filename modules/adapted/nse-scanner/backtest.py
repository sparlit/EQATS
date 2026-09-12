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


"""
============================================================
NSE 3-MINUTE + D-2 1-MINUTE BACKTEST
============================================================

STRATEGY
--------

D-1 = Previous trading day
D-2 = Day before previous trading day
D0  = Trading day on which the trade is executed


D-1 CONDITIONS
--------------

1. 3-minute 15:24 and 15:27 must be opposite trends.

2. 3-minute 15:24 volume must be greater than 15:27 volume.

3. 3-minute 09:15 and 09:18 must BOTH be opposite
   to the 15:24 trend.


D-2 CONDITION
-------------

4. 1-minute 15:28 trend on D-2 must be the SAME as
   the 3-minute 15:24 trend on D-1.


TRADE
-----

5. Enter D0 at 09:15 OPEN.

6. Direction = D-1 15:24 trend.

7. Exit D0 at 15:27 OPEN.

8. No target.

9. No stop loss.

10. No other 1-minute conditions.


3-MINUTE CANDLE CONSTRUCTION
----------------------------

09:15 = 09:15 + 09:16 + 09:17
09:18 = 09:18 + 09:19 + 09:20

...

15:24 = 15:24 + 15:25 + 15:26
15:27 = 15:27 + 15:28 + 15:29


TREND
-----

GREEN:
    Close > Open

RED:
    Close < Open

DOJI:
    Close == Open

Doji does not qualify as either trend.

============================================================
"""


import glob
import os
import warnings
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ============================================================
# CONFIGURATION
# ============================================================

DATA_DIRS = [
    "Nse_Historical_Data",
    "Nse_Historical_Data_2026",
]

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_TRADES = RESULTS_DIR / "trades.csv"
OUTPUT_STOCKS = RESULTS_DIR / "stock_summary.csv"
OUTPUT_DAILY = RESULTS_DIR / "daily_summary.csv"
OUTPUT_SUMMARY = RESULTS_DIR / "summary.txt"
OUTPUT_HTML = RESULTS_DIR / "index.html"


# ------------------------------------------------------------
# Trading cost
# ------------------------------------------------------------
#
# This is deducted from every completed trade.
#
# 0.10 means 0.10% total round-trip cost.
#
# Change to 0.0 if you want raw price returns.
# ------------------------------------------------------------

ROUND_TRIP_COST_PCT = 0.10


# ============================================================
# TIME SETTINGS
# ============================================================

MORNING_TIMES = [
    "09:15",
    "09:18",
]

AFTERNOON_TIMES = [
    "15:24",
    "15:27",
]

D2_1MIN_TIME = "15:28"

ENTRY_TIME = "09:15"
EXIT_TIME = "15:27"


# ============================================================
# TREND
# ============================================================


def candle_trend(open_price, close_price):
    """
    Returns:

        1  = bullish / green
       -1  = bearish / red
        0  = doji / invalid
    """

    if pd.isna(open_price) or pd.isna(close_price):
        return 0

    if close_price > open_price:
        return 1

    if close_price < open_price:
        return -1

    return 0


# ============================================================
# FIND ALL PARQUET FILES
# ============================================================


def find_parquet_files():

    files = []

    print()
    print("=" * 70)
    print("SEARCHING FOR PARQUET FILES")
    print("=" * 70)

    for directory in DATA_DIRS:
        if not os.path.isdir(directory):
            print(f"Directory not found: {directory}")

            continue

        found = glob.glob(os.path.join(directory, "**", "*.parquet"), recursive=True)

        print(f"{directory}: {len(found):,} files")

        files.extend(found)

    files = sorted(set(files))

    print(f"Total Parquet files: {len(files):,}")

    return files


# ============================================================
# NORMALIZE COLUMNS
# ============================================================


def normalize_columns(df):

    df = df.copy()

    # --------------------------------------------------------
    # Flatten MultiIndex columns
    # --------------------------------------------------------

    if isinstance(df.columns, pd.MultiIndex):
        flattened = []

        for col in df.columns:
            parts = []

            for value in col:
                value = str(value)

                if value.lower() != "nan":
                    parts.append(value)

            flattened.append("_".join(parts))

        df.columns = flattened

    # --------------------------------------------------------
    # Detect columns
    # --------------------------------------------------------

    rename_map = {}

    for column in df.columns:
        name = str(column).strip().lower()

        if name in [
            "datetime",
            "date_time",
            "timestamp",
            "time",
            "date",
        ]:
            rename_map[column] = "datetime"

        elif name in [
            "open",
            "open_price",
        ]:
            rename_map[column] = "open"

        elif name in [
            "high",
            "high_price",
        ]:
            rename_map[column] = "high"

        elif name in [
            "low",
            "low_price",
        ]:
            rename_map[column] = "low"

        elif name in [
            "close",
            "close_price",
            "adj close",
            "adj_close",
        ]:
            rename_map[column] = "close"

        elif name in [
            "volume",
            "vol",
        ]:
            rename_map[column] = "volume"

    return df.rename(columns=rename_map)


# ============================================================
# LOAD PARQUET
# ============================================================


def load_parquet(path):

    try:
        df = pd.read_parquet(path)

    except Exception as e:
        print(f"ERROR reading {path}: {e}")

        return None

    df = normalize_columns(df)

    required_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    missing = [column for column in required_columns if column not in df.columns]

    if missing:
        print(f"Skipping {path} - missing: {missing}")

        return None

    # ========================================================
    # DATETIME
    # ========================================================

    if "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"], errors="coerce")

    elif isinstance(df.index, pd.DatetimeIndex):
        dt = pd.Series(pd.to_datetime(df.index, errors="coerce"), index=df.index)

    else:
        print(f"Skipping {path} - datetime not found")

        return None

    # --------------------------------------------------------
    # Remove timezone
    # --------------------------------------------------------

    try:
        if dt.dt.tz is not None:
            dt = dt.dt.tz_localize(None)

    except Exception:
        pass

    df["datetime"] = dt

    # ========================================================
    # NUMERIC DATA
    # ========================================================

    for column in [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    # ========================================================
    # CLEAN
    # ========================================================

    df = df.dropna(
        subset=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    if df.empty:
        return None

    df = df.sort_values("datetime")

    df = df.drop_duplicates(subset=["datetime"], keep="last")

    df = df.set_index("datetime")

    return df


# ============================================================
# GET SYMBOL
# ============================================================


def get_symbol(path):

    name = Path(path).stem.upper()

    suffixes = [
        "_1MIN",
        "_1MINUTE",
        "_MINUTE",
        "_DATA",
        "_HISTORICAL",
    ]

    for suffix in suffixes:
        name = name.removesuffix(suffix)

    return name


# ============================================================
# CREATE 3-MINUTE CANDLES
# ============================================================


def create_3min(df):
    """
    Converts 1-minute NSE data into
    3-minute candles aligned to 09:15.
    """

    data = df.copy()

    # --------------------------------------------------------
    # NSE regular session
    # --------------------------------------------------------

    data = data.between_time("09:15", "15:29")

    if data.empty:
        return pd.DataFrame()

    # ========================================================
    # RESAMPLE
    # ========================================================

    candles = data.resample(
        "3min",
        origin="start_day",
        offset="15min",
        label="left",
        closed="left",
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )

    candles = candles.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
        ]
    )

    # --------------------------------------------------------
    # Keep NSE candle starts
    # --------------------------------------------------------

    return candles[(candles.index.time >= time(9, 15)) & (candles.index.time <= time(15, 27))]


# ============================================================
# GET CANDLE BY TIME
# ============================================================


def get_candle(data, hhmm):

    if data is None or data.empty:
        return None

    matches = data[data.index.strftime("%H:%M") == hhmm]

    if matches.empty:
        return None

    return matches.iloc[0]


# ============================================================
# GET DAILY DATA
# ============================================================


def get_day_data(df, date_value):

    return df[df.index.date == date_value]


# ============================================================
# GET AVAILABLE TRADING DAYS
# ============================================================


def get_trading_days(df):

    if df.empty:
        return []

    return sorted(set(df.index.date))


# ============================================================
# CHECK WHETHER A DAY HAS REQUIRED 3-MIN CANDLES
# ============================================================


def valid_3m_signal_day(day_3m):

    required = [
        "09:15",
        "09:18",
        "15:24",
        "15:27",
    ]

    for hhmm in required:
        candle = get_candle(day_3m, hhmm)

        if candle is None:
            return False

    return True


# ============================================================
# CHECK D-1 SIGNAL
# ============================================================


def check_previous_day_signal(day_3m):
    """
    Check all D-1 conditions.

    Returns a dictionary if valid.
    Otherwise None.
    """

    # ========================================================
    # GET CANDLES
    # ========================================================

    candle_0915 = get_candle(day_3m, "09:15")

    candle_0918 = get_candle(day_3m, "09:18")

    candle_1524 = get_candle(day_3m, "15:24")

    candle_1527 = get_candle(day_3m, "15:27")

    if any(
        candle is None
        for candle in [
            candle_0915,
            candle_0918,
            candle_1524,
            candle_1527,
        ]
    ):
        return None

    # ========================================================
    # TRENDS
    # ========================================================

    trend_0915 = candle_trend(candle_0915["open"], candle_0915["close"])

    trend_0918 = candle_trend(candle_0918["open"], candle_0918["close"])

    trend_1524 = candle_trend(candle_1524["open"], candle_1524["close"])

    trend_1527 = candle_trend(candle_1527["open"], candle_1527["close"])

    # ========================================================
    # 15:24 MUST HAVE VALID TREND
    # ========================================================

    if trend_1524 == 0:
        return None

    # ========================================================
    # CONDITION 1
    #
    # 15:24 AND 15:27 OPPOSITE
    # ========================================================

    if trend_1527 == 0:
        return None

    condition_1 = trend_1524 == -trend_1527

    if not condition_1:
        return None

    # ========================================================
    # CONDITION 2
    #
    # 15:24 VOLUME > 15:27 VOLUME
    # ========================================================

    volume_1524 = float(candle_1524["volume"])

    volume_1527 = float(candle_1527["volume"])

    condition_2 = volume_1524 > volume_1527

    if not condition_2:
        return None

    # ========================================================
    # CONDITION 3
    #
    # BOTH MORNING CANDLES OPPOSITE TO 15:24
    # ========================================================

    condition_3 = trend_0915 != 0 and trend_0918 != 0 and trend_0915 == -trend_1524 and trend_0918 == -trend_1524

    if not condition_3:
        return None

    # ========================================================
    # SIGNAL PASSED
    # ========================================================

    return {
        "direction": trend_1524,
        "trend_0915": trend_0915,
        "trend_0918": trend_0918,
        "trend_1524": trend_1524,
        "trend_1527": trend_1527,
        "volume_1524": volume_1524,
        "volume_1527": volume_1527,
        "volume_ratio": (volume_1524 / volume_1527 if volume_1527 > 0 else np.nan),
    }


# ============================================================
# CHECK D-2 1-MIN CONDITION
# ============================================================


def check_d2_condition(day_d2_1m, required_direction):
    """
    D-2 15:28 1-minute candle must have
    the same trend as D-1 3-minute 15:24.
    """

    candle_1528 = get_candle(day_d2_1m, D2_1MIN_TIME)

    if candle_1528 is None:
        return None

    trend_1528 = candle_trend(candle_1528["open"], candle_1528["close"])

    # Doji does not qualify
    if trend_1528 == 0:
        return None

    if trend_1528 != required_direction:
        return None

    return {
        "trend_1528": trend_1528,
        "open_1528": float(candle_1528["open"]),
        "close_1528": float(candle_1528["close"]),
        "volume_1528": float(candle_1528["volume"]),
    }


# ============================================================
# FIND ENTRY / EXIT
# ============================================================


def get_trade_prices(trade_day_1m):

    entry_candle = get_candle(trade_day_1m, ENTRY_TIME)

    exit_candle = get_candle(trade_day_1m, EXIT_TIME)

    if entry_candle is None:
        return None

    if exit_candle is None:
        return None

    entry_price = float(entry_candle["open"])

    exit_price = float(exit_candle["open"])

    if not np.isfinite(entry_price):
        return None

    if not np.isfinite(exit_price):
        return None

    if entry_price <= 0:
        return None

    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
    }


# ============================================================
# CALCULATE TRADE RETURN
# ============================================================


def calculate_return(entry_price, exit_price, direction):

    if direction == 1:
        # LONG
        gross = ((exit_price - entry_price) / entry_price) * 100

    else:
        # SHORT
        gross = ((entry_price - exit_price) / entry_price) * 100

    net = gross - ROUND_TRIP_COST_PCT

    return gross, net


# ============================================================
# PROCESS ONE STOCK
# ============================================================


def process_stock(path, stock_number, total_stocks):

    symbol = get_symbol(path)

    print(f"[{stock_number}/{total_stocks}] {symbol}")

    # ========================================================
    # LOAD DATA
    # ========================================================

    df = load_parquet(path)

    if df is None or df.empty:
        return []

    # ========================================================
    # CREATE 3-MINUTE DATA
    # ========================================================

    df_3m = create_3min(df)

    if df_3m.empty:
        return []

    # ========================================================
    # TRADING DAYS
    # ========================================================

    trading_days = get_trading_days(df)

    if len(trading_days) < 3:
        return []

    trades = []

    # ========================================================
    # LOOP THROUGH D-1
    #
    # index:
    #
    # i-2 = D-2
    # i-1 = D-1
    # i   = D0
    #
    # We therefore start at index 1.
    # ========================================================

    for i in range(1, len(trading_days) - 1):
        d2 = trading_days[i - 1]

        d1 = trading_days[i]

        d0 = trading_days[i + 1]

        # ====================================================
        # D-1 3-MIN DATA
        # ====================================================

        d1_3m = get_day_data(df_3m, d1)

        if d1_3m.empty:
            continue

        # ====================================================
        # D-1 SIGNAL
        # ====================================================

        signal = check_previous_day_signal(d1_3m)

        if signal is None:
            continue

        direction = signal["direction"]

        # ====================================================
        # D-2 1-MIN DATA
        # ====================================================

        d2_1m = get_day_data(df, d2)

        if d2_1m.empty:
            continue

        # ====================================================
        # D-2 15:28 CONDITION
        # ====================================================

        d2_condition = check_d2_condition(d2_1m, direction)

        if d2_condition is None:
            continue

        # ====================================================
        # D0 TRADE DATA
        # ====================================================

        d0_1m = get_day_data(df, d0)

        if d0_1m.empty:
            continue

        prices = get_trade_prices(d0_1m)

        if prices is None:
            continue

        entry_price = prices["entry_price"]

        exit_price = prices["exit_price"]

        # ====================================================
        # RETURN
        # ====================================================

        gross_return, net_return = calculate_return(entry_price, exit_price, direction)

        win = net_return > 0

        # ====================================================
        # STORE
        # ====================================================

        trades.append(
            {
                "symbol": symbol,
                "d2_date": str(d2),
                "signal_date": str(d1),
                "trade_date": str(d0),
                "direction": ("LONG" if direction == 1 else "SHORT"),
                # D-2
                "d2_15:28_trend": d2_condition["trend_1528"],
                "d2_15:28_open": d2_condition["open_1528"],
                "d2_15:28_close": d2_condition["close_1528"],
                "d2_15:28_volume": d2_condition["volume_1528"],
                # D-1
                "d1_09:15_trend": signal["trend_0915"],
                "d1_09:18_trend": signal["trend_0918"],
                "d1_15:24_trend": signal["trend_1524"],
                "d1_15:27_trend": signal["trend_1527"],
                "d1_15:24_volume": signal["volume_1524"],
                "d1_15:27_volume": signal["volume_1527"],
                "d1_volume_ratio": signal["volume_ratio"],
                # D0 trade
                "entry_time": ENTRY_TIME,
                "exit_time": EXIT_TIME,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_return_pct": gross_return,
                "cost_pct": ROUND_TRIP_COST_PCT,
                "net_return_pct": net_return,
                "win": int(win),
            }
        )

    return trades


# ============================================================
# PROFIT FACTOR
# ============================================================


def calculate_profit_factor(returns):

    returns = pd.Series(returns)

    gross_profit = returns[returns > 0].sum()

    gross_loss = abs(returns[returns < 0].sum())

    if gross_loss == 0:
        if gross_profit > 0:
            return float("inf")

        return 0.0

    return gross_profit / gross_loss


# ============================================================
# MAX DRAWDOWN
# ============================================================


def calculate_max_drawdown(returns):

    returns = pd.Series(returns)

    if returns.empty:
        return 0.0

    equity = (1 + returns / 100).cumprod()

    peak = equity.cummax()

    drawdown = (equity / peak - 1) * 100

    return float(drawdown.min())


# ============================================================
# CREATE SUMMARY
# ============================================================


def create_summary(trades_df):

    if trades_df.empty:
        text = """
============================================================
BACKTEST RESULTS
============================================================

NO QUALIFYING TRADES FOUND.

============================================================
"""

        OUTPUT_SUMMARY.write_text(text, encoding="utf-8")

        print(text)

        return

    returns = trades_df["net_return_pct"]

    total_trades = len(trades_df)

    wins = int(trades_df["win"].sum())

    losses = total_trades - wins

    win_rate = wins / total_trades * 100

    average_return = returns.mean()

    total_return = returns.sum()

    profit_factor = calculate_profit_factor(returns)

    max_drawdown = calculate_max_drawdown(returns)

    best_trade = returns.max()

    worst_trade = returns.min()

    # ========================================================
    # LONG / SHORT
    # ========================================================

    long_trades = trades_df[trades_df["direction"] == "LONG"]

    short_trades = trades_df[trades_df["direction"] == "SHORT"]

    long_win_rate = long_trades["win"].mean() * 100 if len(long_trades) > 0 else 0.0

    short_win_rate = short_trades["win"].mean() * 100 if len(short_trades) > 0 else 0.0

    # ========================================================
    # SIGNAL DIAGNOSTICS
    # ========================================================

    average_volume_ratio = trades_df["d1_volume_ratio"].mean()

    # ========================================================
    # SUMMARY
    # ========================================================

    text = f"""
============================================================
NSE 3-MINUTE + D-2 1-MINUTE STRATEGY
============================================================

STRATEGY
------------------------------------------------------------

D-1:

3-min 15:24 and 15:27:
    Opposite trends

3-min 15:24:
    Volume > 15:27

3-min 09:15:
    Opposite to 15:24

3-min 09:18:
    Opposite to 15:24


D-2:

1-min 15:28:
    Same trend as D-1 3-min 15:24


TRADE:

D0 09:15 OPEN:
    Entry

Direction:
    D-1 15:24 trend

D0 15:27 OPEN:
    Exit

No target.
No stop loss.

------------------------------------------------------------
RESULTS
------------------------------------------------------------

Total trades       : {total_trades:,}

Winning trades     : {wins:,}

Losing trades      : {losses:,}

Win rate           : {win_rate:.2f}%

Average trade      : {average_return:.4f}%

Total return       : {total_return:.4f}%

Profit factor      : {profit_factor:.4f}

Best trade         : {best_trade:.4f}%

Worst trade        : {worst_trade:.4f}%

Maximum drawdown   : {max_drawdown:.4f}%

------------------------------------------------------------
LONG / SHORT
------------------------------------------------------------

Long trades        : {len(long_trades):,}

Long win rate      : {long_win_rate:.2f}%

Short trades       : {len(short_trades):,}

Short win rate     : {short_win_rate:.2f}%

------------------------------------------------------------
SIGNAL DIAGNOSTICS
------------------------------------------------------------

Average
15:24 / 15:27
volume ratio       : {average_volume_ratio:.2f}x

------------------------------------------------------------
COST
------------------------------------------------------------

Round-trip cost    : {ROUND_TRIP_COST_PCT:.2f}%

============================================================
"""

    OUTPUT_SUMMARY.write_text(text, encoding="utf-8")

    print(text)


# ============================================================
# STOCK SUMMARY
# ============================================================


def create_stock_summary(trades_df):

    if trades_df.empty:
        pd.DataFrame().to_csv(OUTPUT_STOCKS, index=False)

        return

    rows = []

    for symbol, group in trades_df.groupby("symbol"):
        returns = group["net_return_pct"]

        trade_count = len(group)

        wins = int(group["win"].sum())

        losses = trade_count - wins

        win_rate = wins / trade_count * 100

        rows.append(
            {
                "symbol": symbol,
                "trades": trade_count,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": win_rate,
                "avg_return_pct": returns.mean(),
                "total_return_pct": returns.sum(),
                "profit_factor": calculate_profit_factor(returns),
                "best_trade_pct": returns.max(),
                "worst_trade_pct": returns.min(),
            }
        )

    summary = pd.DataFrame(rows)

    summary = summary.sort_values(
        [
            "total_return_pct",
            "win_rate_pct",
        ],
        ascending=False,
    )

    summary.to_csv(OUTPUT_STOCKS, index=False)


# ============================================================
# DAILY SUMMARY
# ============================================================


def create_daily_summary(trades_df):

    if trades_df.empty:
        pd.DataFrame().to_csv(OUTPUT_DAILY, index=False)

        return

    daily = (
        trades_df.groupby("trade_date")
        .agg(
            trades=("net_return_pct", "count"),
            wins=("win", "sum"),
            net_return_pct=("net_return_pct", "sum"),
            avg_return_pct=("net_return_pct", "mean"),
        )
        .reset_index()
    )

    daily["losses"] = daily["trades"] - daily["wins"]

    daily["win_rate_pct"] = daily["wins"] / daily["trades"] * 100

    daily = daily.sort_values("trade_date")

    daily.to_csv(OUTPUT_DAILY, index=False)


# ============================================================
# HTML REPORT
# ============================================================


def create_html_report(trades_df):

    if trades_df.empty:
        html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Backtest Results</title>
</head>

<body>

<h1>NSE Strategy Backtest</h1>

<p>No qualifying trades were found.</p>

</body>
</html>
"""

        OUTPUT_HTML.write_text(html, encoding="utf-8")

        return

    returns = trades_df["net_return_pct"]

    total_trades = len(trades_df)

    wins = int(trades_df["win"].sum())

    win_rate = wins / total_trades * 100

    avg_return = returns.mean()

    total_return = returns.sum()

    profit_factor = calculate_profit_factor(returns)

    max_drawdown = calculate_max_drawdown(returns)

    # --------------------------------------------------------
    # Show latest 500 trades
    # --------------------------------------------------------

    latest = trades_df.tail(500)

    table_html = latest.to_html(index=False, classes="trades")

    html = f"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>
NSE 3-Minute + D-2 Strategy
</title>

<style>

body {{
    font-family: Arial, sans-serif;
    background: #f5f5f5;
    margin: 30px;
}}

.container {{
    max-width: 1500px;
    margin: auto;
}}

.card {{
    background: white;
    padding: 20px;
    margin-bottom: 20px;
    border-radius: 10px;
}}

.metric {{
    display: inline-block;
    min-width: 180px;
    padding: 15px;
    margin: 5px;
    background: #fafafa;
    border-radius: 8px;
}}

.metric h3 {{
    margin: 0;
    font-size: 14px;
}}

.metric p {{
    font-size: 24px;
    margin: 10px 0 0 0;
}}

table {{
    border-collapse: collapse;
    width: 100%;
    background: white;
}}

th, td {{
    border: 1px solid #ddd;
    padding: 7px;
    text-align: right;
    white-space: nowrap;
}}

th {{
    background: #eee;
}}

</style>

</head>

<body>

<div class="container">

<div class="card">

<h1>
NSE 3-Minute + D-2 1-Minute Strategy
</h1>

<p>
D-2 15:28 confirmation →
D-1 15:24 signal →
D0 09:15 entry →
D0 15:27 exit
</p>

</div>


<div class="card">

<div class="metric">

<h3>Total Trades</h3>

<p>
{total_trades:,}
</p>

</div>


<div class="metric">

<h3>Win Rate</h3>

<p>
{win_rate:.2f}%
</p>

</div>


<div class="metric">

<h3>Average Trade</h3>

<p>
{avg_return:.4f}%
</p>

</div>


<div class="metric">

<h3>Total Return</h3>

<p>
{total_return:.4f}%
</p>

</div>


<div class="metric">

<h3>Profit Factor</h3>

<p>
{profit_factor:.3f}
</p>

</div>


<div class="metric">

<h3>Max Drawdown</h3>

<p>
{max_drawdown:.4f}%
</p>

</div>

</div>


<div class="card">

<h2>Strategy Conditions</h2>

<ul>

<li>
D-1 3-min 15:24 and 15:27 are opposite.
</li>

<li>
D-1 15:24 volume is greater than 15:27.
</li>

<li>
D-1 09:15 is opposite to 15:24.
</li>

<li>
D-1 09:18 is opposite to 15:24.
</li>

<li>
D-2 1-min 15:28 matches D-1 3-min 15:24.
</li>

<li>
D0 09:15 open entry.
</li>

<li>
D0 15:27 open exit.
</li>

<li>
No target or stop loss.
</li>

</ul>

</div>


<div class="card">

<h2>Trades</h2>

{table_html}

</div>

</div>

</body>

</html>
"""

    OUTPUT_HTML.write_text(html, encoding="utf-8")


# ============================================================
# MAIN
# ============================================================


def main():

    print()
    print("=" * 70)
    print("NSE BACKTEST STARTING")
    print("=" * 70)

    print()
    print("D-1 3-min 15:24 vs 15:27 = OPPOSITE")
    print("D-1 15:24 volume > 15:27 volume")
    print("D-1 09:15 = OPPOSITE to 15:24")
    print("D-1 09:18 = OPPOSITE to 15:24")
    print("D-2 1-min 15:28 = SAME as D-1 3-min 15:24")
    print("D0 09:15 OPEN = ENTRY")
    print("D0 15:27 OPEN = EXIT")
    print("No target / stop loss")
    print()

    # ========================================================
    # FIND DATA
    # ========================================================

    files = find_parquet_files()

    if not files:
        print()
        print("ERROR: No Parquet files found.")

        return

    # ========================================================
    # PROCESS
    # ========================================================

    all_trades = []

    total_files = len(files)

    for number, path in enumerate(files, start=1):
        try:
            trades = process_stock(path, number, total_files)

            if trades:
                all_trades.extend(trades)

        except Exception as e:
            print()
            print(f"ERROR processing {path}")

            print(repr(e))

    # ========================================================
    # DATAFRAME
    # ========================================================

    trades_df = pd.DataFrame(all_trades)

    # ========================================================
    # NO TRADES
    # ========================================================

    if trades_df.empty:
        print()
        print("=" * 70)
        print("BACKTEST COMPLETE")
        print("=" * 70)
        print("No qualifying trades.")

        trades_df.to_csv(OUTPUT_TRADES, index=False)

        create_stock_summary(trades_df)

        create_daily_summary(trades_df)

        create_summary(trades_df)

        create_html_report(trades_df)

        return

    # ========================================================
    # SORT
    # ========================================================

    trades_df = trades_df.sort_values(
        [
            "trade_date",
            "symbol",
        ]
    ).reset_index(drop=True)

    # ========================================================
    # SAVE
    # ========================================================

    trades_df.to_csv(OUTPUT_TRADES, index=False)

    create_stock_summary(trades_df)

    create_daily_summary(trades_df)

    create_summary(trades_df)

    create_html_report(trades_df)

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    returns = trades_df["net_return_pct"]

    wins = int(trades_df["win"].sum())

    print()
    print("=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)

    print(f"Total trades: {len(trades_df):,}")

    print(f"Wins: {wins:,}")

    print(f"Losses: {len(trades_df) - wins:,}")

    print(f"Win rate: {trades_df['win'].mean() * 100:.2f}%")

    print(f"Average return: {returns.mean():.4f}%")

    print(f"Total return: {returns.sum():.4f}%")

    print(f"Profit factor: {calculate_profit_factor(returns):.4f}")

    print(f"Maximum drawdown: {calculate_max_drawdown(returns):.4f}%")

    print()
    print("Files created:")
    print(f"  {OUTPUT_TRADES}")
    print(f"  {OUTPUT_STOCKS}")
    print(f"  {OUTPUT_DAILY}")
    print(f"  {OUTPUT_SUMMARY}")
    print(f"  {OUTPUT_HTML}")

    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
