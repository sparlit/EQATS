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

import pandas as pd

# ============================================================
# JOHN'S BACKTEST V2
# ============================================================

ROOT = Path(__file__).resolve().parent

DATA_FILE = ROOT / "data" / "sample_ohlcv.csv"
SIGNALS_FILE = ROOT / "output" / "scanner_results.csv"

OUTPUT_CSV = ROOT / "output" / "backtest_results.csv"
OUTPUT_HTML = ROOT / "output" / "backtest.html"

MAX_BARS = 20

TP1_PART = 0.50
TP2_PART = 0.50


# ============================================================
# LOAD DATA
# ============================================================

print()
print("=" * 60)
print("JOHN'S BACKTEST V2")
print("=" * 60)

if not DATA_FILE.exists():
    raise FileNotFoundError(f"Missing OHLCV file: {DATA_FILE}")

if not SIGNALS_FILE.exists():
    raise FileNotFoundError(f"Missing scanner results: {SIGNALS_FILE}")

ohlcv = pd.read_csv(DATA_FILE)
signals = pd.read_csv(SIGNALS_FILE)

print(f"OHLCV rows: {len(ohlcv)}")
print(f"Signals: {len(signals)}")


# ============================================================
# NORMALIZE OHLCV
# ============================================================

ohlcv.columns = [str(c).strip().lower() for c in ohlcv.columns]

required = ["symbol", "date", "open", "high", "low", "close"]

missing = [c for c in required if c not in ohlcv.columns]

if missing:
    raise ValueError(f"OHLCV missing columns: {missing}")

ohlcv["symbol"] = ohlcv["symbol"].astype(str).str.strip().str.upper()

ohlcv["date"] = pd.to_datetime(ohlcv["date"], errors="coerce")

for col in ["open", "high", "low", "close"]:
    ohlcv[col] = pd.to_numeric(ohlcv[col], errors="coerce")

ohlcv = ohlcv.dropna(subset=["symbol", "date", "open", "high", "low", "close"])

ohlcv = ohlcv.sort_values(["symbol", "date"])


# ============================================================
# FIND SIGNAL COLUMNS
# ============================================================


def find_column(df, choices):

    lookup = {str(c).strip().lower(): c for c in df.columns}

    for name in choices:
        if name.lower() in lookup:
            return lookup[name.lower()]

    return None


symbol_col = find_column(signals, ["stock", "symbol"])

entry_col = find_column(signals, ["entry"])

sl_col = find_column(signals, ["sl", "stop_loss", "stop loss"])

tp1_col = find_column(signals, ["tp1", "tp 1"])

tp2_col = find_column(signals, ["tp2", "tp 2"])

confirmation_col = find_column(signals, ["confirmation", "confirmation_date", "confirmation date"])


required_signal_columns = {
    "symbol": symbol_col,
    "entry": entry_col,
    "SL": sl_col,
    "TP1": tp1_col,
    "TP2": tp2_col,
    "confirmation": confirmation_col,
}

for name, col in required_signal_columns.items():
    if col is None:
        raise ValueError(f"Could not find signal column: {name}")


# ============================================================
# PREPARE SIGNALS
# ============================================================

signals["symbol"] = signals[symbol_col].astype(str).str.strip().str.upper()

signals["entry_price"] = pd.to_numeric(signals[entry_col], errors="coerce")

signals["sl_price"] = pd.to_numeric(signals[sl_col], errors="coerce")

signals["tp1_price"] = pd.to_numeric(signals[tp1_col], errors="coerce")

signals["tp2_price"] = pd.to_numeric(signals[tp2_col], errors="coerce")

signals["signal_date"] = pd.to_datetime(signals[confirmation_col], errors="coerce")

signals = signals.dropna(
    subset=["symbol", "entry_price", "sl_price", "tp1_price", "tp2_price", "signal_date"]
)


# ============================================================
# BACKTEST
# ============================================================

results = []

print()
print("Running historical test...")
print()


for _, signal in signals.iterrows():
    symbol = signal["symbol"]

    signal_date = signal["signal_date"]

    entry = float(signal["entry_price"])
    sl = float(signal["sl_price"])
    tp1 = float(signal["tp1_price"])
    tp2 = float(signal["tp2_price"])

    stock = ohlcv[ohlcv["symbol"] == symbol].copy()

    future = stock[stock["date"] > signal_date].head(MAX_BARS)

    # --------------------------------------------------------
    # NO FUTURE DATA
    # --------------------------------------------------------

    if future.empty:
        results.append(
            {
                "symbol": symbol,
                "signal_date": signal_date,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "status": "NO FUTURE DATA",
                "tp1_hit": False,
                "tp2_hit": False,
                "sl_hit": False,
                "tp1_date": None,
                "tp2_date": None,
                "sl_date": None,
                "bars_to_tp1": None,
                "bars_to_tp2": None,
                "bars_to_sl": None,
                "exit_date": None,
                "exit_price": None,
                "return_pct": None,
                "max_up_pct": None,
                "max_down_pct": None,
            }
        )

        continue

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    tp1_hit = False
    tp2_hit = False
    sl_hit = False

    tp1_date = None
    tp2_date = None
    sl_date = None

    bars_to_tp1 = None
    bars_to_tp2 = None
    bars_to_sl = None

    status = "OPEN"

    exit_date = None
    exit_price = None

    realised_return = 0.0

    max_high = entry
    min_low = entry

    # --------------------------------------------------------
    # FOLLOW FUTURE CANDLES
    # --------------------------------------------------------

    for bar_number, (_, bar) in enumerate(future.iterrows(), start=1):
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        bar_date = bar["date"]

        max_high = max(max_high, high)
        min_low = min(min_low, low)

        hit_sl = low <= sl
        hit_tp1 = high >= tp1
        hit_tp2 = high >= tp2

        # ----------------------------------------------------
        # SL BEFORE TP1
        # ----------------------------------------------------

        if not tp1_hit and hit_sl:
            sl_hit = True
            sl_date = bar_date
            bars_to_sl = bar_number

            status = "SL BEFORE TP1"

            exit_date = bar_date
            exit_price = sl

            realised_return = (sl - entry) / entry * 100

            break

        # ----------------------------------------------------
        # TP1
        # ----------------------------------------------------

        if not tp1_hit and hit_tp1:
            tp1_hit = True

            tp1_date = bar_date
            bars_to_tp1 = bar_number

            realised_return += TP1_PART * ((tp1 - entry) / entry * 100)

            # TP2 on same candle

            if hit_tp2:
                tp2_hit = True

                tp2_date = bar_date
                bars_to_tp2 = bar_number

                realised_return += TP2_PART * ((tp2 - entry) / entry * 100)

                status = "TP2"

                exit_date = bar_date
                exit_price = tp2

                break

            continue

        # ----------------------------------------------------
        # AFTER TP1
        # ----------------------------------------------------

        if tp1_hit:
            # TP2

            if hit_tp2:
                tp2_hit = True

                tp2_date = bar_date
                bars_to_tp2 = bar_number

                realised_return += TP2_PART * ((tp2 - entry) / entry * 100)

                status = "TP2"

                exit_date = bar_date
                exit_price = tp2

                break

            # Remaining half hits SL

            if hit_sl:
                sl_hit = True

                sl_date = bar_date
                bars_to_sl = bar_number

                realised_return += TP2_PART * ((sl - entry) / entry * 100)

                status = "TP1 -> SL"

                exit_date = bar_date
                exit_price = sl

                break

    # --------------------------------------------------------
    # STILL OPEN
    # --------------------------------------------------------

    if status == "OPEN":
        last_bar = future.iloc[-1]

        exit_date = last_bar["date"]

        exit_price = float(last_bar["close"])

        remaining_return = (exit_price - entry) / entry * 100

        if tp1_hit:
            realised_return += TP2_PART * remaining_return

            status = "TP1 -> OPEN"

        else:
            realised_return = remaining_return

    # --------------------------------------------------------
    # MAX MOVE
    # --------------------------------------------------------

    max_up_pct = (max_high - entry) / entry * 100

    max_down_pct = (min_low - entry) / entry * 100

    results.append(
        {
            "symbol": symbol,
            "signal_date": signal_date,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "status": status,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "sl_hit": sl_hit,
            "tp1_date": tp1_date,
            "tp2_date": tp2_date,
            "sl_date": sl_date,
            "bars_to_tp1": bars_to_tp1,
            "bars_to_tp2": bars_to_tp2,
            "bars_to_sl": bars_to_sl,
            "exit_date": exit_date,
            "exit_price": exit_price,
            "return_pct": realised_return,
            "max_up_pct": max_up_pct,
            "max_down_pct": max_down_pct,
        }
    )


# ============================================================
# RESULTS
# ============================================================

df = pd.DataFrame(results)

if df.empty:
    print("No results generated.")
    raise SystemExit(0)


# ============================================================
# SAVE CSV
# ============================================================

df.to_csv(OUTPUT_CSV, index=False)


# ============================================================
# STATISTICS
# ============================================================

total = len(df)

tp1_count = int(df["tp1_hit"].sum())

tp2_count = int(df["tp2_hit"].sum())

sl_before_tp1 = int((df["status"] == "SL BEFORE TP1").sum())

tp1_then_sl = int((df["status"] == "TP1 -> SL").sum())

tp1_open = int((df["status"] == "TP1 -> OPEN").sum())

no_future = int((df["status"] == "NO FUTURE DATA").sum())

usable = total - no_future


if usable > 0:
    tp1_rate = tp1_count / usable * 100

    tp2_rate = tp2_count / usable * 100

else:
    tp1_rate = 0
    tp2_rate = 0


closed = df[df["status"] != "NO FUTURE DATA"]


average_return = closed["return_pct"].mean() if not closed.empty else 0


avg_bars_tp1 = df["bars_to_tp1"].dropna().mean()

avg_bars_tp2 = df["bars_to_tp2"].dropna().mean()

avg_max_up = df["max_up_pct"].dropna().mean()

avg_max_down = df["max_down_pct"].dropna().mean()


# ============================================================
# FORMAT DATE COLUMNS
# ============================================================

for col in ["signal_date", "tp1_date", "tp2_date", "sl_date", "exit_date"]:
    df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")


# ============================================================
# BUILD TABLE
# ============================================================

table_rows = []

for _, row in df.iterrows():
    symbol = html.escape(str(row["symbol"]))

    status = html.escape(str(row["status"]))

    table_rows.append(
        "<tr>"
        f"<td><b>{symbol}</b></td>"
        f"<td>{row['signal_date']}</td>"
        f"<td>₹{row['entry']:.2f}</td>"
        f"<td>₹{row['sl']:.2f}</td>"
        f"<td>₹{row['tp1']:.2f}</td>"
        f"<td>₹{row['tp2']:.2f}</td>"
        f"<td><b>{status}</b></td>"
        f"<td>{row['tp1_date']}</td>"
        f"<td>{row['tp2_date']}</td>"
        f"<td>{row['bars_to_tp1']}</td>"
        f"<td>{row['bars_to_tp2']}</td>"
        f"<td>{row['return_pct']:.2f}%</td>"
        f"<td>{row['max_up_pct']:.2f}%</td>"
        f"<td>{row['max_down_pct']:.2f}%</td>"
        "</tr>"
    )

table_html = "\n".join(table_rows)


# ============================================================
# HTML DASHBOARD
# ============================================================

html_page = """
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>John's Backtest V2</title>

<style>

body {
    margin: 0;
    background: #090e1c;
    color: #e8edf7;
    font-family: Arial, sans-serif;
}

.container {
    padding: 20px;
}

h1 {
    margin-bottom: 5px;
}

.subtitle {
    color: #9ca8bf;
    margin-bottom: 20px;
}

.cards {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(145px, 1fr));
    gap: 12px;
    margin-bottom: 25px;
}

.card {
    background: #161c2d;
    border: 1px solid #29334b;
    border-radius: 10px;
    padding: 15px;
}

.title {
    color: #9ba7bc;
    font-size: 12px;
}

.value {
    font-size: 23px;
    font-weight: bold;
    margin-top: 7px;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    background: #151b2b;
}

th {
    background: #11172a;
    color: #aab4c9;
    padding: 11px;
    text-align: left;
    white-space: nowrap;
}

td {
    padding: 9px;
    border-top: 1px solid #29334b;
    white-space: nowrap;
}

.note {
    margin-top: 20px;
    padding: 15px;
    background: #11172a;
    border-radius: 8px;
    color: #929db2;
    line-height: 1.6;
}

</style>

</head>

<body>

<div class="container">

<h1>📊 JOHN'S BACKTEST V2</h1>

<div class="subtitle">
EMA50 → Pullback → RSI → Volume → Confirmation
<br>
50% at TP1 → remaining 50% at TP2 or SL
</div>

<div class="cards">

<div class="card">
<div class="title">TOTAL SIGNALS</div>
<div class="value">__TOTAL__</div>
</div>

<div class="card">
<div class="title">TP1 HIT</div>
<div class="value">__TP1__</div>
</div>

<div class="card">
<div class="title">TP1 RATE</div>
<div class="value">__TP1RATE__%</div>
</div>

<div class="card">
<div class="title">TP2 HIT</div>
<div class="value">__TP2__</div>
</div>

<div class="card">
<div class="title">TP2 RATE</div>
<div class="value">__TP2RATE__%</div>
</div>

<div class="card">
<div class="title">SL BEFORE TP1</div>
<div class="value">__SL__</div>
</div>

<div class="card">
<div class="title">TP1 → SL</div>
<div class="value">__TP1SL__</div>
</div>

<div class="card">
<div class="title">TP1 → OPEN</div>
<div class="value">__TP1OPEN__</div>
</div>

<div class="card">
<div class="title">AVERAGE RETURN</div>
<div class="value">__RETURN__%</div>
</div>

<div class="card">
<div class="title">AVG BARS TP1</div>
<div class="value">__BARSTP1__</div>
</div>

<div class="card">
<div class="title">AVG BARS TP2</div>
<div class="value">__BARSTP2__</div>
</div>

</div>

<div class="table-wrap">

<table>

<thead>

<tr>
<th>STOCK</th>
<th>SIGNAL</th>
<th>ENTRY</th>
<th>SL</th>
<th>TP1</th>
<th>TP2</th>
<th>RESULT</th>
<th>TP1 DATE</th>
<th>TP2 DATE</th>
<th>BARS TP1</th>
<th>BARS TP2</th>
<th>RETURN</th>
<th>MAX UP</th>
<th>MAX DOWN</th>
</tr>

</thead>

<tbody>

__TABLE__

</tbody>

</table>

</div>

<div class="note">

<b>Backtest V2 methodology</b>

<br><br>

The test uses only candles after the
confirmation date.

50% of the position is considered
booked at TP1.

The remaining 50% continues toward TP2
or SL.

If SL occurs before TP1, the complete
position is treated as stopped.

Maximum tracking period:
20 trading bars.

Same-candle ambiguity is handled
conservatively.

This is historical research and does
not guarantee future performance.

</div>

</div>

</body>

</html>
"""


# ============================================================
# INSERT DATA INTO HTML
# ============================================================

html_page = html_page.replace("__TOTAL__", str(total))

html_page = html_page.replace("__TP1__", str(tp1_count))

html_page = html_page.replace("__TP1RATE__", f"{tp1_rate:.2f}")

html_page = html_page.replace("__TP2__", str(tp2_count))

html_page = html_page.replace("__TP2RATE__", f"{tp2_rate:.2f}")

html_page = html_page.replace("__SL__", str(sl_before_tp1))

html_page = html_page.replace("__TP1SL__", str(tp1_then_sl))

html_page = html_page.replace("__TP1OPEN__", str(tp1_open))

html_page = html_page.replace("__RETURN__", f"{average_return:.2f}")

html_page = html_page.replace("__BARSTP1__", f"{avg_bars_tp1:.2f}")

html_page = html_page.replace("__BARSTP2__", f"{avg_bars_tp2:.2f}")

html_page = html_page.replace("__TABLE__", table_html)


# ============================================================
# SAVE HTML
# ============================================================

OUTPUT_HTML.write_text(html_page, encoding="utf-8")


# ============================================================
# FINAL REPORT
# ============================================================

print()
print("=" * 60)
print("BACKTEST V2 COMPLETE")
print("=" * 60)

print(f"Total signals       : {total}")
print(f"TP1 hit             : {tp1_count}")
print(f"TP1 hit rate        : {tp1_rate:.2f}%")
print(f"TP2 hit             : {tp2_count}")
print(f"TP2 hit rate        : {tp2_rate:.2f}%")
print(f"SL before TP1       : {sl_before_tp1}")
print(f"TP1 -> SL           : {tp1_then_sl}")
print(f"TP1 -> OPEN         : {tp1_open}")
print(f"No future data      : {no_future}")
print(f"Average return      : {average_return:.2f}%")
print(f"Average bars TP1    : {avg_bars_tp1:.2f}")
print(f"Average bars TP2    : {avg_bars_tp2:.2f}")
print(f"Average max upside  : {avg_max_up:.2f}%")
print(f"Average max downside: {avg_max_down:.2f}%")

print()
print(f"CSV : {OUTPUT_CSV}")
print(f"HTML: {OUTPUT_HTML}")

print()
print("Backtest V2 finished successfully.")
print("=" * 60)
