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

TRADE_CSV = OUTPUT_DIR / "backtest_v4_results.csv"
SUMMARY_CSV = OUTPUT_DIR / "backtest_v4_summary.csv"
HTML_FILE = OUTPUT_DIR / "backtest_v4.html"

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


def pct(value):

    return round(float(value), 2)


print()
print("==========================================")
print("JOHN BACKTEST V4")
print("EXIT MODEL COMPARISON")
print("==========================================")
print()

if not DATA_FILE.exists():
    raise FileNotFoundError("Missing file: " + str(DATA_FILE))


df = pd.read_csv(DATA_FILE)

print("OHLCV rows :", len(df))
print("Stocks     :", df["symbol"].nunique())
print()


df["date"] = pd.to_datetime(df["date"], errors="coerce")

for col in ["open", "high", "low", "close", "volume"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")


df = df.dropna(subset=["symbol", "date", "open", "high", "low", "close", "volume"])


df = df.sort_values(["symbol", "date"])


all_trades = []


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

        initial_sl = pullback_low

        future = stock.iloc[i + 1 : i + 1 + MAX_HOLD]

        if future.empty:
            continue

        used_crosses.add(cross_index)

        model_a_return = None
        model_b_return = None
        model_c_return = None

        model_a_status = ""
        model_b_status = ""
        model_c_status = ""

        model_a_exit = None
        model_b_exit = None
        model_c_exit = None

        model_a_date = None
        model_b_date = None
        model_c_date = None

        model_a_bars = None
        model_b_bars = None
        model_c_bars = None

        model_a_max_high = entry
        model_a_min_low = entry

        model_b_max_high = entry
        model_b_min_low = entry

        model_c_max_high = entry
        model_c_min_low = entry

        a_done = False
        b_done = False
        c_done = False

        a_tp1 = False
        a_tp2 = False

        b_tp1 = False
        b_tp2 = False
        b_be = False

        c_tp1 = False
        c_tp2 = False
        c_sl = False
        c_be = False

        a_realized = 0.0
        b_realized = 0.0
        c_realized = 0.0

        a_remaining = 1.0
        b_remaining = 1.0
        c_remaining = 1.0

        for bar, (_, candle) in enumerate(future.iterrows(), start=1):
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
            current_date = candle["date"]

            model_a_max_high = max(model_a_max_high, high)

            model_a_min_low = min(model_a_min_low, low)

            model_b_max_high = max(model_b_max_high, high)

            model_b_min_low = min(model_b_min_low, low)

            model_c_max_high = max(model_c_max_high, high)

            model_c_min_low = min(model_c_min_low, low)

            # ==================================
            # MODEL A
            # CURRENT NO-SL MODEL
            # ==================================

            if not a_done:
                if not a_tp1 and high >= tp1:
                    a_tp1 = True

                    a_realized += 0.50 * ((tp1 - entry) / entry) * 100

                    a_remaining = 0.50

                if a_tp1 and not a_tp2 and high >= tp2:
                    a_tp2 = True

                    a_realized += 0.50 * ((tp2 - entry) / entry) * 100

                    a_remaining = 0.0

                    model_a_return = a_realized

                    model_a_status = "TP2 HIT"

                    model_a_exit = tp2

                    model_a_date = current_date

                    model_a_bars = bar

                    a_done = True

                if not a_done and bar >= MAX_HOLD:
                    if a_tp1:
                        a_realized += 0.50 * ((close - entry) / entry) * 100

                        model_a_return = a_realized

                        model_a_status = "TP1 + FINAL"

                    else:
                        model_a_return = ((close - entry) / entry) * 100

                        model_a_status = "NO TP"

                    model_a_exit = close

                    model_a_date = current_date

                    model_a_bars = bar

                    a_done = True

            # ==================================
            # MODEL B
            # TP1 -> BREAKEVEN
            # ==================================

            if not b_done:
                if not b_tp1 and high >= tp1:
                    b_tp1 = True

                    b_realized += 0.50 * ((tp1 - entry) / entry) * 100

                    b_remaining = 0.50

                if b_tp1 and not b_tp2 and not b_be:
                    # Conservative intrabar assumption:
                    # if both BE and TP2 occur in same candle,
                    # BE is treated as happening first.

                    if low <= entry:
                        b_be = True

                        b_realized += 0.50 * 0.0

                        model_b_return = b_realized

                        model_b_status = "TP1 + BE"

                        model_b_exit = entry

                        model_b_date = current_date

                        model_b_bars = bar

                        b_done = True

                    elif high >= tp2:
                        b_tp2 = True

                        b_realized += 0.50 * ((tp2 - entry) / entry) * 100

                        model_b_return = b_realized

                        model_b_status = "TP2 HIT"

                        model_b_exit = tp2

                        model_b_date = current_date

                        model_b_bars = bar

                        b_done = True

                if not b_done and bar >= MAX_HOLD:
                    if b_tp1:
                        b_realized += 0.50 * ((close - entry) / entry) * 100

                        model_b_return = b_realized

                        model_b_status = "TP1 + FINAL"

                    else:
                        model_b_return = ((close - entry) / entry) * 100

                        model_b_status = "NO TP"

                    model_b_exit = close

                    model_b_date = current_date

                    model_b_bars = bar

                    b_done = True

            # ==================================
            # MODEL C
            # PULLBACK SL -> BREAKEVEN
            # ==================================

            if not c_done:
                if not c_tp1:
                    # Conservative assumption:
                    # SL is checked before TP1 if both
                    # occur during the same candle.

                    if low <= initial_sl:
                        c_sl = True

                        model_c_return = ((initial_sl - entry) / entry) * 100

                        model_c_status = "INITIAL SL"

                        model_c_exit = initial_sl

                        model_c_date = current_date

                        model_c_bars = bar

                        c_done = True

                    elif high >= tp1:
                        c_tp1 = True

                        c_realized += 0.50 * ((tp1 - entry) / entry) * 100

                        c_remaining = 0.50

                if c_tp1 and not c_tp2 and not c_be:
                    # After TP1, remaining half is at breakeven.

                    if low <= entry:
                        c_be = True

                        model_c_return = c_realized

                        model_c_status = "TP1 + BE"

                        model_c_exit = entry

                        model_c_date = current_date

                        model_c_bars = bar

                        c_done = True

                    elif high >= tp2:
                        c_tp2 = True

                        c_realized += 0.50 * ((tp2 - entry) / entry) * 100

                        model_c_return = c_realized

                        model_c_status = "TP2 HIT"

                        model_c_exit = tp2

                        model_c_date = current_date

                        model_c_bars = bar

                        c_done = True

                if not c_done and bar >= MAX_HOLD:
                    if c_tp1:
                        c_realized += 0.50 * ((close - entry) / entry) * 100

                        model_c_return = c_realized

                        model_c_status = "TP1 + FINAL"

                    else:
                        model_c_return = ((close - entry) / entry) * 100

                        model_c_status = "NO TP"

                    model_c_exit = close

                    model_c_date = current_date

                    model_c_bars = bar

                    c_done = True

            if a_done and b_done and c_done:
                break

        if not a_done:
            continue

        all_trades.append(
            {
                "symbol": symbol,
                "ema_cross_date": stock.loc[cross_index, "date"].strftime("%Y-%m-%d"),
                "pullback_date": stock.loc[pullback_index, "date"].strftime("%Y-%m-%d"),
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "entry": pct(entry),
                "pullback_low": pct(pullback_low),
                "risk": pct(risk),
                "tp1": pct(tp1),
                "tp2": pct(tp2),
                "rsi": pct(rsi),
                "volume_ratio": pct(vol_ratio),
                "model_a_status": model_a_status,
                "model_a_exit": pct(model_a_exit),
                "model_a_date": model_a_date.strftime("%Y-%m-%d"),
                "model_a_bars": model_a_bars,
                "model_a_return_pct": pct(model_a_return),
                "model_a_max_upside_pct": pct(((model_a_max_high - entry) / entry) * 100),
                "model_a_max_downside_pct": pct(((model_a_min_low - entry) / entry) * 100),
                "model_b_status": model_b_status,
                "model_b_exit": pct(model_b_exit),
                "model_b_date": model_b_date.strftime("%Y-%m-%d"),
                "model_b_bars": model_b_bars,
                "model_b_return_pct": pct(model_b_return),
                "model_b_max_upside_pct": pct(((model_b_max_high - entry) / entry) * 100),
                "model_b_max_downside_pct": pct(((model_b_min_low - entry) / entry) * 100),
                "model_c_status": model_c_status,
                "model_c_exit": pct(model_c_exit),
                "model_c_date": model_c_date.strftime("%Y-%m-%d"),
                "model_c_bars": model_c_bars,
                "model_c_return_pct": pct(model_c_return),
                "model_c_max_upside_pct": pct(((model_c_max_high - entry) / entry) * 100),
                "model_c_max_downside_pct": pct(((model_c_min_low - entry) / entry) * 100),
            }
        )

    if number % 25 == 0:
        print("Processed:", number, "Stocks | Trades:", len(all_trades))


OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


trades = pd.DataFrame(all_trades)


if trades.empty:
    print()
    print("NO TRADES FOUND")
    print()

    raise SystemExit(0)


trades.to_csv(TRADE_CSV, index=False)


# ==========================================
# SUMMARY FUNCTION
# ==========================================


def make_summary(prefix, name):

    returns = pd.to_numeric(trades[prefix + "_return_pct"], errors="coerce")

    status = trades[prefix + "_status"].astype(str)

    total = len(trades)

    positive = (returns > 0).sum()

    negative = (returns < 0).sum()

    zero = (returns == 0).sum()

    tp2 = status.eq("TP2 HIT").sum()

    tp1 = status.str.startswith("TP1").sum()

    initial_sl = status.eq("INITIAL SL").sum()

    be = status.eq("TP1 + BE").sum()

    no_tp = status.eq("NO TP").sum()

    avg_return = returns.mean()

    median_return = returns.median()

    avg_upside = pd.to_numeric(trades[prefix + "_max_upside_pct"], errors="coerce").mean()

    avg_downside = pd.to_numeric(trades[prefix + "_max_downside_pct"], errors="coerce").mean()

    avg_bars = pd.to_numeric(trades[prefix + "_bars"], errors="coerce").mean()

    return {
        "model": name,
        "total_trades": total,
        "positive_trades": positive,
        "positive_pct": positive / total * 100,
        "negative_trades": negative,
        "negative_pct": negative / total * 100,
        "zero_trades": zero,
        "tp2_hits": tp2,
        "tp2_pct": tp2 / total * 100,
        "tp1_related": tp1,
        "tp1_related_pct": tp1 / total * 100,
        "breakeven_exits": be,
        "initial_sl_exits": initial_sl,
        "no_tp": no_tp,
        "average_return_pct": avg_return,
        "median_return_pct": median_return,
        "average_max_upside_pct": avg_upside,
        "average_max_downside_pct": avg_downside,
        "average_bars": avg_bars,
    }


summary = pd.DataFrame(
    [
        make_summary("model_a", "A - CURRENT NO SL"),
        make_summary("model_b", "B - TP1 THEN BREAKEVEN"),
        make_summary("model_c", "C - PULLBACK SL THEN BREAKEVEN"),
    ]
)


summary = summary.round(2)


summary.to_csv(SUMMARY_CSV, index=False)


# ==========================================
# HTML
# ==========================================


def esc(value):

    return html.escape(str(value))


html_lines = []

html_lines.append("<!DOCTYPE html>")
