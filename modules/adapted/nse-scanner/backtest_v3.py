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


import html
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent

DATA_FILE = ROOT / "data" / "sample_ohlcv.csv"
OUTPUT_DIR = ROOT / "output"

OUTPUT_CSV = OUTPUT_DIR / "backtest_v3_results.csv"
OUTPUT_HTML = OUTPUT_DIR / "backtest_v3.html"

EMA_LEN = 50
RSI_LEN = 14
VOL_LEN = 20

VOL_MULT = 1.5
PULLBACK_TOL = 0.01

MAX_SETUP = 5
MAX_PULLBACK = 3
MAX_HOLD = 60


def rsi_wilder(close, length):

    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    return 100 - (100 / (1 + rs))


print()
print("====================================")
print("JOHN BACKTEST V3")
print("====================================")
print()

if not DATA_FILE.exists():
    raise FileNotFoundError("Missing file: " + str(DATA_FILE))

df = pd.read_csv(DATA_FILE)

print("Rows:", len(df))
print("Stocks:", df["symbol"].nunique())
print()

df["date"] = pd.to_datetime(df["date"], errors="coerce")

for col in ["open", "high", "low", "close", "volume"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(subset=["symbol", "date", "open", "high", "low", "close", "volume"])

df = df.sort_values(["symbol", "date"])

results = []

for number, (symbol, stock) in enumerate(df.groupby("symbol"), start=1):
    stock = stock.copy()

    stock = stock.sort_values("date").reset_index(drop=True)

    if len(stock) < 80:
        continue

    stock["ema50"] = stock["close"].ewm(span=EMA_LEN, adjust=False).mean()

    stock["rsi"] = rsi_wilder(stock["close"], RSI_LEN)

    stock["vol_avg"] = stock["volume"].rolling(VOL_LEN).mean()

    stock["vol_ratio"] = stock["volume"] / stock["vol_avg"]

    stock["cross"] = (stock["close"] > stock["ema50"]) & (
        stock["close"].shift(1) <= stock["ema50"].shift(1)
    )

    used_crosses = set()

    for i in range(EMA_LEN + VOL_LEN, len(stock)):
        cross_index = None

        start = max(0, i - MAX_SETUP)

        for j in range(i, start - 1, -1):
            if stock.loc[j, "cross"]:
                cross_index = j
                break

        if cross_index is None:
            continue

        if cross_index in used_crosses:
            continue

        pullback_index = None

        start_pb = cross_index + 1

        end_pb = min(len(stock) - 1, cross_index + MAX_PULLBACK)

        for j in range(start_pb, end_pb + 1):
            ema = stock.loc[j, "ema50"]
            low = stock.loc[j, "low"]

            if pd.isna(ema):
                continue

            distance = abs(low - ema) / ema

            if distance <= PULLBACK_TOL:
                pullback_index = j
                break

        if pullback_index is None:
            continue

        rsi = stock.loc[i, "rsi"]

        if pd.isna(rsi):
            continue

        if rsi <= 50:
            continue

        vol_ratio = stock.loc[i, "vol_ratio"]

        if pd.isna(vol_ratio):
            continue

        if vol_ratio < VOL_MULT:
            continue

        if stock.loc[i, "close"] <= stock.loc[i, "open"]:
            continue

        entry = float(stock.loc[i, "close"])

        entry_date = stock.loc[i, "date"]

        pullback_low = float(stock.loc[pullback_index, "low"])

        risk = entry - pullback_low

        if risk <= 0:
            continue

        tp1 = entry + risk
        tp2 = entry + (risk * 2)

        future = stock.iloc[i + 1 : i + 1 + MAX_HOLD]

        if future.empty:
            continue

        tp1_hit = False
        tp2_hit = False

        tp1_bar = None
        tp2_bar = None

        max_high = entry
        min_low = entry

        last_close = entry
        last_date = entry_date

        for bar, (_, candle) in enumerate(future.iterrows(), start=1):
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])

            last_close = close
            last_date = candle["date"]

            max_high = max(max_high, high)

            min_low = min(min_low, low)

            if not tp1_hit and high >= tp1:
                tp1_hit = True
                tp1_bar = bar

            if not tp2_hit and high >= tp2:
                tp2_hit = True
                tp2_bar = bar

                break

        if tp2_hit:
            status = "TP2 HIT"

            exit_price = tp2

            return_pct = ((tp1 - entry) / entry) * 50 + ((tp2 - entry) / entry) * 50

        elif tp1_hit:
            status = "TP1 HIT"

            exit_price = tp1

            return_pct = ((tp1 - entry) / entry) * 50 + ((last_close - entry) / entry) * 50

        else:
            status = "OPEN"

            exit_price = last_close

            return_pct = (last_close - entry) / entry * 100

        max_upside = (max_high - entry) / entry * 100

        max_downside = (min_low - entry) / entry * 100

        results.append(
            {
                "symbol": symbol,
                "ema_cross_date": stock.loc[cross_index, "date"].strftime("%Y-%m-%d"),
                "pullback_date": stock.loc[pullback_index, "date"].strftime("%Y-%m-%d"),
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "entry": round(entry, 2),
                "pullback_low": round(pullback_low, 2),
                "risk": round(risk, 2),
                "tp1": round(tp1, 2),
                "tp2": round(tp2, 2),
                "status": status,
                "bars_to_tp1": tp1_bar if tp1_hit else "",
                "bars_to_tp2": tp2_bar if tp2_hit else "",
                "exit_date": last_date.strftime("%Y-%m-%d"),
                "exit_price": round(exit_price, 2),
                "return_pct": round(return_pct, 2),
                "max_upside_pct": round(max_upside, 2),
                "max_downside_pct": round(max_downside, 2),
            }
        )

        used_crosses.add(cross_index)

    if number % 25 == 0:
        print("Processed:", number, "Stocks | Signals:", len(results))


OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

result_df = pd.DataFrame(results)

if result_df.empty:
    result_df = pd.DataFrame(
        columns=[
            "symbol",
            "ema_cross_date",
            "pullback_date",
            "entry_date",
            "entry",
            "pullback_low",
            "risk",
            "tp1",
            "tp2",
            "status",
            "bars_to_tp1",
            "bars_to_tp2",
            "exit_date",
            "exit_price",
            "return_pct",
            "max_upside_pct",
            "max_downside_pct",
        ]
    )

    result_df.to_csv(OUTPUT_CSV, index=False)

    print()
    print("NO SIGNALS FOUND")
    print("CSV created:", OUTPUT_CSV)
    print()

    raise SystemExit(0)


result_df.to_csv(OUTPUT_CSV, index=False)


total = len(result_df)

tp1_count = result_df[result_df["status"].isin(["TP1 HIT", "TP2 HIT"])].shape[0]

tp2_count = result_df[result_df["status"] == "TP2 HIT"].shape[0]

open_count = result_df[result_df["status"] == "OPEN"].shape[0]

tp1_rate = tp1_count / total * 100

tp2_rate = tp2_count / total * 100

avg_return = result_df["return_pct"].mean()

avg_upside = result_df["max_upside_pct"].mean()

avg_downside = result_df["max_downside_pct"].mean()

bars1 = pd.to_numeric(result_df["bars_to_tp1"], errors="coerce").dropna()

bars2 = pd.to_numeric(result_df["bars_to_tp2"], errors="coerce").dropna()

avg_bars1 = bars1.mean() if len(bars1) else 0

avg_bars2 = bars2.mean() if len(bars2) else 0


def safe(value):
    return html.escape(str(value))


rows = []

for _, row in result_df.iterrows():
    status = str(row["status"])

    rows.append(
        "<tr>"
        "<td>" + safe(row["symbol"]) + "</td>"
        "<td>" + safe(row["ema_cross_date"]) + "</td>"
        "<td>" + safe(row["pullback_date"]) + "</td>"
        "<td>" + safe(row["entry_date"]) + "</td>"
        "<td>" + safe(row["entry"]) + "</td>"
        "<td>" + safe(row["pullback_low"]) + "</td>"
        "<td>" + safe(row["tp1"]) + "</td>"
        "<td>" + safe(row["tp2"]) + "</td>"
        "<td>" + safe(status) + "</td>"
        "<td>" + safe(row["bars_to_tp1"]) + "</td>"
        "<td>" + safe(row["bars_to_tp2"]) + "</td>"
        "<td>" + safe(row["exit_date"]) + "</td>"
        "<td>" + safe(row["exit_price"]) + "</td>"
        "<td>" + safe(row["return_pct"]) + "%</td>"
        "<td>" + safe(row["max_upside_pct"]) + "%</td>"
        "<td>" + safe(row["max_downside_pct"]) + "%</td>"
        "</tr>"
    )


table_rows = "\n".join(rows)


html_lines = []

html_lines.append("<!DOCTYPE html>")
html_lines.append("<html>")
html_lines.append("<head>")
html_lines.append('<meta charset="UTF-8">')
html_lines.append("<title>John Backtest V3</title>")

html_lines.append("<style>")
html_lines.append(
    "body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:0;padding:20px}"
)
html_lines.append(".container{max-width:1600px;margin:auto}")
html_lines.append("h1{margin-bottom:5px}")
html_lines.append(".sub{color:#aaa;margin-bottom:20px}")
html_lines.append(
    ".cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}"
)
html_lines.append(".card{background:#1d1d1d;padding:16px;border-radius:10px}")
html_lines.append(".label{color:#999;font-size:12px}")
html_lines.append(".value{font-size:24px;font-weight:bold;margin-top:5px}")
html_lines.append(
    ".download{display:inline-block;padding:10px 15px;background:#333;color:#fff;text-decoration:none;border-radius:7px;margin-bottom:20px}"
)
html_lines.append(".tablebox{overflow-x:auto;background:#181818;border-radius:10px}")
html_lines.append("table{border-collapse:collapse;width:100%;min-width:1500px}")
html_lines.append("th{background:#252525;position:sticky;top:0;padding:10px;text-align:left}")
html_lines.append("td{border-bottom:1px solid #333;padding:9px;white-space:nowrap}")
html_lines.append("tr:hover{background:#222}")
html_lines.append("</style>")

html_lines.append("</head>")
html_lines.append("<body>")
html_lines.append('<div class="container">')

html_lines.append("<h1>JOHN'S BACKTEST V3</h1>")

html_lines.append(
    '<div class="sub">'
    "EMA50 Cross → Pullback → RSI &gt; 50 → Volume ≥ 1.5× → Bullish Confirmation"
    "</div>"
)

html_lines.append(
    '<a class="download" href="backtest_v3_results.csv" download>📥 DOWNLOAD BACKTEST CSV</a>'
)

html_lines.append('<div class="cards">')

cards = [
    ("TOTAL SIGNALS", total),
    ("TP1 HIT", str(tp1_count) + " (" + f"{tp1_rate:.2f}" + "%)"),
    ("TP2 HIT", str(tp2_count) + " (" + f"{tp2_rate:.2f}" + "%)"),
    ("STILL OPEN", open_count),
    ("AVG RETURN", f"{avg_return:.2f}%"),
    ("AVG BARS TP1", f"{avg_bars1:.2f}"),
    ("AVG BARS TP2", f"{avg_bars2:.2f}"),
    ("AVG MAX UPSIDE", f"{avg_upside:.2f}%"),
    ("AVG MAX DOWNSIDE", f"{avg_downside:.2f}%"),
]

for label, value in cards:
    html_lines.append(
        '<div class="card">'
        '<div class="label">' + safe(label) + "</div>"
        '<div class="value">' + safe(value) + "</div>"
        "</div>"
    )

html_lines.append("</div>")

html_lines.append(
    "<p>Entry = confirmation candle close | Stop loss = NONE | Maximum holding = 60 bars</p>"
)

html_lines.append('<div class="tablebox">')
html_lines.append("<table>")

headers = [
    "STOCK",
    "EMA CROSS",
    "PULLBACK",
    "ENTRY DATE",
    "ENTRY",
    "PULLBACK LOW",
    "TP1",
    "TP2",
    "STATUS",
    "BARS TP1",
    "BARS TP2",
    "EXIT DATE",
    "EXIT PRICE",
    "RETURN %",
    "MAX UPSIDE %",
    "MAX DOWNSIDE %",
]

html_lines.append("<thead><tr>")

for header in headers:
    html_lines.append("<th>" + header + "</th>")

html_lines.append("</tr></thead>")

html_lines.append("<tbody>")
html_lines.append(table_rows)
html_lines.append("</tbody>")

html_lines.append("</table>")
html_lines.append("</div>")

html_lines.append("</div>")
html_lines.append("</body>")
html_lines.append("</html>")


OUTPUT_HTML.write_text("\n".join(html_lines), encoding="utf-8")


print()
print("====================================")
print("JOHN BACKTEST V3 COMPLETE")
print("====================================")
print()

print("Total signals       :", total)

print("TP1 reached         :", tp1_count)

print("TP1 hit rate        :", f"{tp1_rate:.2f}%")

print("TP2 reached         :", tp2_count)

print("TP2 hit rate        :", f"{tp2_rate:.2f}%")

print("Still open          :", open_count)

print("Average return      :", f"{avg_return:.2f}%")

print("Average bars TP1    :", f"{avg_bars1:.2f}")

print("Average bars TP2    :", f"{avg_bars2:.2f}")

print("Average max upside  :", f"{avg_upside:.2f}%")

print("Average max down    :", f"{avg_downside:.2f}%")

print()

print("CSV :", OUTPUT_CSV)
print("HTML:", OUTPUT_HTML)

print()

print("====================================")
print("BACKTEST V3 FINISHED")
print("====================================")
