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


import json
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent

CONFIG_FILE = ROOT / "config.json"
UNIVERSE_FILE = ROOT / "universe.csv"
DATA_FILE = ROOT / "data" / "sample_ohlcv.csv"

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

RESULT_FILE = OUTPUT_DIR / "scanner_results.csv"
STATE_FILE = OUTPUT_DIR / "scanner_state.json"
HTML_FILE = OUTPUT_DIR / "index.html"


# ---------------------------------------------------------
# LOAD CONFIGURATION
# ---------------------------------------------------------

with open(CONFIG_FILE, encoding="utf-8") as f:
    CONFIG = json.load(f)


EMA_LENGTH = CONFIG["ema_length"]
RSI_LENGTH = CONFIG["rsi_length"]
VOLUME_AVG_LENGTH = CONFIG["volume_average_length"]

VOLUME_MULTIPLIER = CONFIG["volume_multiplier"]
PULLBACK_TOLERANCE = CONFIG["pullback_tolerance_pct"]

MAX_SETUP_BARS = CONFIG["max_setup_bars"]
MAX_PULLBACK_BARS = CONFIG["max_pullback_bars"]

FRESH_BARS = CONFIG["fresh_bars"]
AGED_BARS = CONFIG["aged_bars"]

REQUIRE_BULLISH = CONFIG["require_bullish_confirmation"]


# ---------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------


def calculate_indicators(df):

    df = df.sort_values("date").copy()

    # EMA 50
    df["ema50"] = df["close"].ewm(span=EMA_LENGTH, adjust=False).mean()

    # RSI
    delta = df["close"].diff()

    gain = delta.clip(lower=0).rolling(RSI_LENGTH).mean()

    loss = -delta.clip(upper=0).rolling(RSI_LENGTH).mean()

    rs = gain / loss.replace(0, np.nan)

    df["rsi"] = 100 - (100 / (1 + rs))

    # Volume average
    df["volume_avg"] = df["volume"].rolling(VOLUME_AVG_LENGTH).mean()

    df["volume_ratio"] = df["volume"] / df["volume_avg"]

    # EMA 50 cross
    df["ema_cross"] = (df["close"] > df["ema50"]) & (df["close"].shift(1) <= df["ema50"].shift(1))

    return df


# ---------------------------------------------------------
# SCAN ONE STOCK
# ---------------------------------------------------------


def scan_stock(df):

    df = calculate_indicators(df)

    signals = []

    cross_index = None
    pullback_index = None

    for i in range(len(df)):
        # ---------------------------------------------
        # EMA 50 CROSS
        # ---------------------------------------------

        if bool(df["ema_cross"].iloc[i]):
            cross_index = i
            pullback_index = None

        if cross_index is None:
            continue

        # Too much time after EMA cross
        if i - cross_index > MAX_SETUP_BARS:
            cross_index = None
            pullback_index = None

            continue

        ema50 = df["ema50"].iloc[i]
        low = df["low"].iloc[i]
        close = df["close"].iloc[i]

        # ---------------------------------------------
        # PULLBACK
        # ---------------------------------------------

        pullback = low <= ema50 * (1 + PULLBACK_TOLERANCE / 100) and close >= ema50

        if pullback:
            pullback_index = i

        if pullback_index is None:
            continue

        # Pullback became too old
        if i - pullback_index > MAX_PULLBACK_BARS:
            pullback_index = None

            continue

        # ---------------------------------------------
        # RSI CROSS ABOVE 50
        # ---------------------------------------------

        if i > 0:
            previous_rsi = df["rsi"].iloc[i - 1]
            current_rsi = df["rsi"].iloc[i]

        # Check if RSI crossed after EMA cross
        rsi_after_ema = False

        for j in range(cross_index, i + 1):
            if j == 0:
                continue

            previous_rsi = df["rsi"].iloc[j - 1]
            current_rsi = df["rsi"].iloc[j]

            if current_rsi > 50 and previous_rsi <= 50:
                rsi_after_ema = True
                break

        # ---------------------------------------------
        # GOOD VOLUME
        # ---------------------------------------------

        volume_ratio = df["volume_ratio"].iloc[i]

        good_volume = not pd.isna(volume_ratio) and volume_ratio >= VOLUME_MULTIPLIER

        # ---------------------------------------------
        # BULLISH CANDLE
        # ---------------------------------------------

        bullish = True

        if REQUIRE_BULLISH:
            bullish = df["close"].iloc[i] > df["open"].iloc[i]

        # ---------------------------------------------
        # FINAL CONFIRMATION
        # ---------------------------------------------

        confirmation = (
            pullback_index is not None
            and df["close"].iloc[i] > df["ema50"].iloc[i]
            and bullish
            and df["rsi"].iloc[i] > 50
            and rsi_after_ema
            and good_volume
        )

        if confirmation:
            signals.append(
                {
                    "confirmation_index": i,
                    "ema_cross_index": cross_index,
                    "pullback_index": pullback_index,
                    "entry": float(df["close"].iloc[i]),
                    "pullback_low": float(df["low"].iloc[pullback_index]),
                    "rsi": float(df["rsi"].iloc[i]),
                    "volume_ratio": float(df["volume_ratio"].iloc[i]),
                }
            )

            # Reset after confirmation
            cross_index = None
            pullback_index = None

    return df, signals


# ---------------------------------------------------------
# DATE FORMAT
# ---------------------------------------------------------


def format_date(value):

    return pd.Timestamp(value).strftime("%d-%b-%Y")


# ---------------------------------------------------------
# BUILD RESULTS
# ---------------------------------------------------------


def build_results():

    universe = pd.read_csv(UNIVERSE_FILE)

    data = pd.read_csv(DATA_FILE, parse_dates=["date"])

    results = []

    for _, stock in universe.iterrows():
        symbol = stock["symbol"]
        sector = stock["sector"]

        stock_data = data[data["symbol"] == symbol].copy()

        if len(stock_data) < EMA_LENGTH + 5:
            continue

        df, signals = scan_stock(stock_data)

        if not signals:
            continue

        signal = signals[-1]

        ema_index = signal["ema_cross_index"]

        pullback_index = signal["pullback_index"]

        confirmation_index = signal["confirmation_index"]

        entry = signal["entry"]

        pullback_low = signal["pullback_low"]

        # -----------------------------------------
        # STOP LOSS
        # -----------------------------------------

        stop_loss = pullback_low * 0.9975

        risk = entry - stop_loss

        # -----------------------------------------
        # TARGETS
        # -----------------------------------------

        tp1 = entry + risk
        tp2 = entry + (risk * 2)

        # -----------------------------------------
        # SIGNAL AGE
        # -----------------------------------------

        age = len(df) - 1 - confirmation_index

        if age <= FRESH_BARS:
            status = "FRESH"

        elif age <= AGED_BARS:
            status = "AGED"

        else:
            status = "ENDED"

        results.append(
            {
                "symbol": symbol,
                "sector": sector,
                "ema_cross": format_date(df.iloc[ema_index]["date"]),
                "pullback": format_date(df.iloc[pullback_index]["date"]),
                "confirmation": format_date(df.iloc[confirmation_index]["date"]),
                "entry": entry,
                "sl": stop_loss,
                "tp1": tp1,
                "tp2": tp2,
                "rsi": signal["rsi"],
                "volume": signal["volume_ratio"],
                "age": age,
                "status": status,
            }
        )

    return pd.DataFrame(results)


# ---------------------------------------------------------
# BUILD WEBSITE
# ---------------------------------------------------------


def create_dashboard(df):

    if df.empty:
        table_html = """
        <div class="empty">
            No qualifying setups found.
        </div>
        """

    else:
        df = df.sort_values(["status", "confirmation"], ascending=[True, False])

        rows = []

        for _, row in df.iterrows():
            status = row["status"].lower()

            rows.append(f"""
            <tr class="{status}">

                <td>
                    <b>{escape(str(row["symbol"]))}</b>
                </td>

                <td>
                    {escape(str(row["sector"]))}
                </td>

                <td>
                    {row["ema_cross"]}
                </td>

                <td>
                    {row["pullback"]}
                </td>

                <td>
                    {row["confirmation"]}
                </td>

                <td>
                    ₹{row["entry"]:.2f}
                </td>

                <td>
                    ₹{row["sl"]:.2f}
                </td>

                <td>
                    ₹{row["tp1"]:.2f}
                </td>

                <td>
                    ₹{row["tp2"]:.2f}
                </td>

                <td>
                    {row["rsi"]:.1f}
                </td>

                <td>
                    {row["volume"]:.1f}x
                </td>

                <td>
                    {int(row["age"])} bar
                </td>

                <td>
                    <b>{row["status"]}</b>
                </td>

            </tr>
            """)

        table_html = (
            """
        <table>

        <thead>

        <tr>

        <th>STOCK</th>
        <th>SECTOR</th>
        <th>EMA CROSS</th>
        <th>PULLBACK</th>
        <th>CONFIRMATION</th>
        <th>ENTRY</th>
        <th>SL</th>
        <th>TP1</th>
        <th>TP2</th>
        <th>RSI</th>
        <th>VOL</th>
        <th>AGE</th>
        <th>STATUS</th>

        </tr>

        </thead>

        <tbody>

        """
            + "".join(rows)
            + """

        </tbody>

        </table>
        """
        )

    html = f"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>
JOHN'S MARKET SCANNER
</title>

<style>

body {{

    margin: 0;

    background: #0b1020;

    color: #e8edf7;

    font-family: Arial, sans-serif;

}}

header {{

    padding: 22px;

    background: #111a31;

    border-bottom:
        1px solid #273453;

}}

h1 {{

    margin: 0;

    font-size: 22px;

}}

.subtitle {{

    margin-top: 7px;

    opacity: .65;

    font-size: 12px;

}}

.container {{

    padding: 20px;

}}

.tabs {{

    display: flex;

    gap: 8px;

    margin-bottom: 15px;

}}

.tab {{

    padding: 10px 15px;

    background: #17213b;

    border-radius: 8px;

    font-size: 12px;

}}

.active {{

    background: #245b39;

}}

.panel {{

    background: #111a31;

    border:
        1px solid #273453;

    border-radius: 12px;

    padding: 14px;

    overflow-x: auto;

}}

table {{

    width: 100%;

    border-collapse: collapse;

    font-size: 11px;

    min-width: 1100px;

}}

th, td {{

    padding: 9px 7px;

    border-bottom:
        1px solid #202b45;

    text-align: left;

    white-space: nowrap;

}}

th {{

    color: #9eacc9;

}}

tr.fresh {{

    background:
        rgba(0,180,90,.12);

}}

tr.aged {{

    background:
        rgba(220,150,0,.10);

}}

tr.ended {{

    background:
        rgba(180,50,50,.08);

}}

.fresh td:last-child {{

    color: #62ff9a;

}}

.aged td:last-child {{

    color: #ffc04d;

}}

.ended td:last-child {{

    color: #ff7272;

}}

.empty {{

    padding: 30px;

    text-align: center;

    opacity: .7;

}}

</style>

</head>

<body>

<header>

<h1>
JOHN'S MARKET SCANNER
</h1>

<div class="subtitle">

GitHub Test V1 —
EMA50 → Pullback → RSI > 50 →
Good Volume → Confirmation

</div>

</header>

<div class="container">

<div class="tabs">

<div class="tab active">
🚀 EMA PULLBACK
</div>

<div class="tab">
🔄 SUPPORT BOUNCE
</div>

</div>

<div class="panel">

{table_html}

</div>

</div>

</body>

</html>
"""

    HTML_FILE.write_text(html, encoding="utf-8")


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------


def main():

    print()
    print("==============================")
    print(" JOHN'S NSE SCANNER V1")
    print("==============================")
    print()

    results = build_results()

    results.to_csv(RESULT_FILE, index=False)

    STATE_FILE.write_text(results.to_json(orient="records", indent=2), encoding="utf-8")

    create_dashboard(results)

    print("Stocks scanned:", len(pd.read_csv(UNIVERSE_FILE)))

    print("Candidates found:", len(results))

    print("Dashboard:", HTML_FILE)

    print()


if __name__ == "__main__":
    main()
