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
# JOHN'S BACKTEST - NO STOP LOSS
# ============================================================

ROOT = Path(__file__).resolve().parent

DATA_FILE = ROOT / "data" / "sample_ohlcv.csv"
SIGNALS_FILE = ROOT / "output" / "scanner_results.csv"

OUTPUT_CSV = ROOT / "output" / "backtest_no_sl_results.csv"
OUTPUT_HTML = ROOT / "output" / "backtest_no_sl.html"

# ------------------------------------------------------------
# BACKTEST SETTINGS
# ------------------------------------------------------------

# Hold for up to 60 bars after the signal.
MAX_BARS = 60

# TP1 and TP2 are taken from the scanner results.
# We are NOT using the stop loss.
TP1_PART = 0.50
TP2_PART = 0.50


# ============================================================
# HELPERS
# ============================================================


def find_column(df, possible_names):

    lower_map = {str(c).strip().lower(): c for c in df.columns}

    for name in possible_names:
        if name.lower() in lower_map:
            return lower_map[name.lower()]

    return None


def clean_number(value):

    try:
        return float(value)
    except Exception:
        return None


# ============================================================
# LOAD DATA
# ============================================================

if not DATA_FILE.exists():
    msg = f"OHLCV file not found: {DATA_FILE}"
    raise FileNotFoundError(msg)

if not SIGNALS_FILE.exists():
    msg = f"Scanner results not found: {SIGNALS_FILE}"
    raise FileNotFoundError(msg)


data = pd.read_csv(DATA_FILE)
signals = pd.read_csv(SIGNALS_FILE)


# ============================================================
# IDENTIFY COLUMNS
# ============================================================

data_symbol_col = find_column(data, ["symbol", "stock", "ticker"])

data_date_col = find_column(data, ["date", "datetime", "timestamp"])

data_open_col = find_column(data, ["open"])

data_high_col = find_column(data, ["high"])

data_low_col = find_column(data, ["low"])

data_close_col = find_column(data, ["close"])


signal_symbol_col = find_column(signals, ["symbol", "stock", "ticker"])

signal_entry_col = find_column(signals, ["entry", "entry_price"])

signal_tp1_col = find_column(signals, ["tp1", "tp_1", "target1"])

signal_tp2_col = find_column(signals, ["tp2", "tp_2", "target2"])

signal_date_col = find_column(signals, ["confirmation", "confirmation_date", "signal_date", "date", "datetime"])


required_data = [data_symbol_col, data_date_col, data_open_col, data_high_col, data_low_col, data_close_col]

required_signals = [signal_symbol_col, signal_entry_col, signal_tp1_col, signal_tp2_col, signal_date_col]


if any(x is None for x in required_data):
    msg = "Could not identify required OHLCV columns."
    raise ValueError(msg)

if any(x is None for x in required_signals):
    msg = "Could not identify required scanner result columns."
    raise ValueError(msg)


# ============================================================
# CLEAN DATA
# ============================================================

data[data_date_col] = pd.to_datetime(data[data_date_col], errors="coerce")

signals[signal_date_col] = pd.to_datetime(signals[signal_date_col], errors="coerce")

data = data.dropna(subset=[data_symbol_col, data_date_col, data_high_col, data_low_col, data_close_col])

signals = signals.dropna(subset=[signal_symbol_col, signal_date_col, signal_entry_col, signal_tp1_col, signal_tp2_col])

data = data.sort_values([data_symbol_col, data_date_col])

signals = signals.sort_values([signal_symbol_col, signal_date_col])


# ============================================================
# BACKTEST
# ============================================================

results = []

total_signals = len(signals)

print()
print("==============================================")
print("JOHN'S BACKTEST - NO STOP LOSS")
print("==============================================")
print()
print(f"Signals loaded: {total_signals}")
print(f"Maximum holding period: {MAX_BARS} bars")
print("Stop Loss: DISABLED")
print()


for _index, signal in signals.iterrows():
    symbol = str(signal[signal_symbol_col]).strip()

    signal_date = signal[signal_date_col]

    entry = clean_number(signal[signal_entry_col])

    tp1 = clean_number(signal[signal_tp1_col])

    tp2 = clean_number(signal[signal_tp2_col])

    if entry is None or tp1 is None or tp2 is None:
        continue

    # --------------------------------------------------------
    # Get stock candles
    # --------------------------------------------------------

    stock_data = data[data[data_symbol_col].astype(str).str.strip() == symbol].copy()

    if stock_data.empty:
        continue

    stock_data = stock_data.sort_values(data_date_col)

    # Only candles AFTER the confirmation/signal date.
    future = stock_data[stock_data[data_date_col] > signal_date].copy()

    if future.empty:
        results.append(
            {
                "symbol": symbol,
                "signal_date": signal_date,
                "entry": entry,
                "tp1": tp1,
                "tp2": tp2,
                "status": "NO FUTURE DATA",
                "bars_to_tp1": "",
                "bars_to_tp2": "",
                "exit_date": "",
                "exit_price": "",
                "return_pct": "",
                "max_upside_pct": "",
                "max_downside_pct": "",
            }
        )

        continue

    # Only examine MAX_BARS candles.
    future = future.head(MAX_BARS).copy()

    tp1_hit = False
    tp2_hit = False

    tp1_bar = None
    tp2_bar = None

    tp1_date = None
    tp2_date = None

    max_high = entry
    min_low = entry

    final_close = None
    final_date = None

    # --------------------------------------------------------
    # Walk forward through candles
    # --------------------------------------------------------

    for bar_number, (_, candle) in enumerate(future.iterrows(), start=1):
        high = clean_number(candle[data_high_col])

        low = clean_number(candle[data_low_col])

        close = clean_number(candle[data_close_col])

        candle_date = candle[data_date_col]

        if high is None or low is None:
            continue

        max_high = max(max_high, high)

        min_low = min(min_low, low)

        final_close = close
        final_date = candle_date

        # ----------------------------------------------------
        # TP1
        # ----------------------------------------------------

        if not tp1_hit and high >= tp1:
            tp1_hit = True
            tp1_bar = bar_number
            tp1_date = candle_date

            print(f"TP1 -> {symbol} | {signal_date.date()} | bar {bar_number}")

        # ----------------------------------------------------
        # TP2
        # ----------------------------------------------------

        if not tp2_hit and high >= tp2:
            tp2_hit = True
            tp2_bar = bar_number
            tp2_date = candle_date

        # ----------------------------------------------------
        # Once TP2 is reached, trade is complete.
        # ----------------------------------------------------

        if tp2_hit:
            break

    # ========================================================
    # DETERMINE RESULT
    # ========================================================

    if tp2_hit:
        status = "TP2 HIT"

        exit_price = tp2
        exit_date = tp2_date

        # 50% at TP1 + 50% at TP2
        return_pct = TP1_PART * ((tp1 - entry) / entry * 100) + TP2_PART * ((tp2 - entry) / entry * 100)

    elif tp1_hit:
        status = "TP1 HIT"

        exit_price = tp1
        exit_date = tp1_date

        # We assume 50% is booked at TP1.
        # Remaining 50% is valued at the final close.
        remaining_return = 0

        if final_close is not None:
            remaining_return = (final_close - entry) / entry * 100

        tp1_return = (tp1 - entry) / entry * 100

        return_pct = TP1_PART * tp1_return + TP2_PART * remaining_return

    else:
        status = "OPEN"

        exit_price = final_close
        exit_date = final_date

        return_pct = (final_close - entry) / entry * 100 if final_close is not None else None

    # --------------------------------------------------------
    # Maximum movement
    # --------------------------------------------------------

    max_upside_pct = (max_high - entry) / entry * 100

    max_downside_pct = (min_low - entry) / entry * 100

    results.append(
        {
            "symbol": symbol,
            "signal_date": signal_date,
            "entry": round(entry, 4),
            "tp1": round(tp1, 4),
            "tp2": round(tp2, 4),
            "status": status,
            "bars_to_tp1": tp1_bar if tp1_hit else "",
            "bars_to_tp2": tp2_bar if tp2_hit else "",
            "tp1_date": tp1_date if tp1_hit else "",
            "tp2_date": tp2_date if tp2_hit else "",
            "exit_date": exit_date if exit_date is not None else "",
            "exit_price": round(exit_price, 4) if exit_price is not None else "",
            "return_pct": round(return_pct, 4) if return_pct is not None else "",
            "max_upside_pct": round(max_upside_pct, 4),
            "max_downside_pct": round(max_downside_pct, 4),
        }
    )


# ============================================================
# RESULTS DATAFRAME
# ============================================================

results_df = pd.DataFrame(results)


if results_df.empty:
    print()
    print("No backtest results were generated.")

    raise SystemExit(0)


# ============================================================
# STATISTICS
# ============================================================

total = len(results_df)

tp1_count = results_df["status"].eq("TP1 HIT").sum()

tp2_count = results_df["status"].eq("TP2 HIT").sum()

open_count = results_df["status"].eq("OPEN").sum()

no_data_count = results_df["status"].eq("NO FUTURE DATA").sum()

tp1_total = tp1_count + tp2_count

tp1_hit_rate = tp1_total / total * 100 if total else 0

tp2_hit_rate = tp2_count / total * 100 if total else 0


valid_returns = pd.to_numeric(results_df["return_pct"], errors="coerce").dropna()

average_return = valid_returns.mean() if not valid_returns.empty else 0


tp1_bars = pd.to_numeric(results_df["bars_to_tp1"], errors="coerce").dropna()

tp2_bars = pd.to_numeric(results_df["bars_to_tp2"], errors="coerce").dropna()


average_bars_tp1 = tp1_bars.mean() if not tp1_bars.empty else 0

average_bars_tp2 = tp2_bars.mean() if not tp2_bars.empty else 0


max_upside = pd.to_numeric(results_df["max_upside_pct"], errors="coerce").dropna()

max_downside = pd.to_numeric(results_df["max_downside_pct"], errors="coerce").dropna()


average_max_upside = max_upside.mean() if not max_upside.empty else 0

average_max_downside = max_downside.mean() if not max_downside.empty else 0


# ============================================================
# SAVE CSV
# ============================================================

OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

results_df.to_csv(OUTPUT_CSV, index=False)


# ============================================================
# HTML DASHBOARD
# ============================================================

rows_html = ""

for _, row in results_df.iterrows():
    rows_html += f"""
    <tr>
        <td>{html.escape(str(row["symbol"]))}</td>
        <td>{html.escape(str(row["signal_date"]))}</td>
        <td>{row["entry"]}</td>
        <td>{row["tp1"]}</td>
        <td>{row["tp2"]}</td>
        <td>{html.escape(str(row["status"]))}</td>
        <td>{row["bars_to_tp1"]}</td>
        <td>{row["bars_to_tp2"]}</td>
        <td>{row["return_pct"]}</td>
        <td>{row["max_upside_pct"]}</td>
        <td>{row["max_downside_pct"]}</td>
    </tr>
    """


html_page = f"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>
John's Backtest - No Stop Loss
</title>

<style>

body {{
    background:#0b0f14;
    color:#e8eef5;
    font-family:Arial,sans-serif;
    margin:30px;
}}

h1 {{
    margin-bottom:5px;
}}

.subtitle {{
    color:#9aa7b5;
    margin-bottom:25px;
}}

.cards {{
    display:grid;
    grid-template-columns:
        repeat(auto-fit,minmax(180px,1fr));
    gap:15px;
    margin-bottom:30px;
}}

.card {{
    background:#151b23;
    border:1px solid #27313d;
    border-radius:12px;
    padding:18px;
}}

.card .label {{
    color:#8e9aaa;
    font-size:13px;
}}

.card .value {{
    font-size:25px;
    font-weight:bold;
    margin-top:7px;
}}

.table-container {{
    overflow-x:auto;
}}

table {{
    width:100%;
    border-collapse:collapse;
    background:#11161d;
}}

th {{
    background:#1b232d;
    padding:10px;
    text-align:left;
    white-space:nowrap;
}}

td {{
    padding:9px;
    border-bottom:1px solid #222a34;
    white-space:nowrap;
}}

tr:hover {{
    background:#18202a;
}}

.note {{
    margin-top:25px;
    padding:15px;
    background:#151b23;
    border-radius:10px;
    color:#aeb9c6;
}}

</style>

</head>


<body>

<h1>
JOHN'S BACKTEST — NO STOP LOSS
</h1>

<div class="subtitle">

Maximum holding period:
<b>{MAX_BARS} bars</b>

&nbsp; | &nbsp;

Stop Loss:
<b>DISABLED</b>

</div>


<div class="cards">

<div class="card">
<div class="label">TOTAL SIGNALS</div>
<div class="value">{total}</div>
</div>


<div class="card">
<div class="label">TP1 HIT</div>
<div class="value">
{tp1_total}
</div>
</div>


<div class="card">
<div class="label">TP1 HIT RATE</div>
<div class="value">
{tp1_hit_rate:.2f}%
</div>
</div>


<div class="card">
<div class="label">TP2 HIT</div>
<div class="value">
{tp2_count}
</div>
</div>


<div class="card">
<div class="label">TP2 HIT RATE</div>
<div class="value">
{tp2_hit_rate:.2f}%
</div>
</div>


<div class="card">
<div class="label">OPEN</div>
<div class="value">
{open_count}
</div>
</div>


<div class="card">
<div class="label">AVG RETURN</div>
<div class="value">
{average_return:.2f}%
</div>
</div>


<div class="card">
<div class="label">AVG BARS TO TP1</div>
<div class="value">
{average_bars_tp1:.2f}
</div>
</div>


<div class="card">
<div class="label">AVG BARS TO TP2</div>
<div class="value">
{average_bars_tp2:.2f}
</div>
</div>


<div class="card">
<div class="label">AVG MAX UPSIDE</div>
<div class="value">
{average_max_upside:.2f}%
</div>
</div>


<div class="card">
<div class="label">AVG MAX DOWNSIDE</div>
<div class="value">
{average_max_downside:.2f}%
</div>
</div>

</div>


<div class="note">

<b>Important:</b>

No stop loss is used in this test.

TP1 is considered reached when a future candle's
high reaches TP1.

TP2 is considered reached when a future candle's
high reaches TP2.

Maximum holding period is {MAX_BARS} bars.

</div>


<h2>Individual Signals</h2>


<div class="table-container">

<table>

<thead>

<tr>

<th>Stock</th>
<th>Signal Date</th>
<th>Entry</th>
<th>TP1</th>
<th>TP2</th>
<th>Status</th>
<th>Bars TP1</th>
<th>Bars TP2</th>
<th>Return %</th>
<th>Max Upside %</th>
<th>Max Downside %</th>

</tr>

</thead>

<tbody>

{rows_html}

</tbody>

</table>

</div>

</body>

</html>
"""


OUTPUT_HTML.write_text(html_page, encoding="utf-8")


# ============================================================
# FINAL CONSOLE REPORT
# ============================================================

print()
print("==============================================")
print("BACKTEST COMPLETE")
print("==============================================")
print()

print(f"Total signals       : {total}")
print(f"TP1 reached        : {tp1_total}")
print(f"TP1 hit rate       : {tp1_hit_rate:.2f}%")
print(f"TP2 reached        : {tp2_count}")
print(f"TP2 hit rate       : {tp2_hit_rate:.2f}%")
print(f"Still open         : {open_count}")
print(f"No future data     : {no_data_count}")

print()

print(f"Average return     : {average_return:.2f}%")

print(f"Average bars TP1   : {average_bars_tp1:.2f}")

print(f"Average bars TP2   : {average_bars_tp2:.2f}")

print(f"Average max upside : {average_max_upside:.2f}%")

print(f"Average max down   : {average_max_downside:.2f}%")

print()

print(f"CSV: {OUTPUT_CSV}")

print(f"HTML: {OUTPUT_HTML}")

print()
print("==============================================")
