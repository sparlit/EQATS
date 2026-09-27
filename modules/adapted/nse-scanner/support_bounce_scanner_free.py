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
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

# When run by GitHub Actions this env var is auto-set — use it to skip
# the "Press Enter to exit" prompts, which would hang the workflow forever.
RUNNING_IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def wait_for_exit():
    if not RUNNING_IN_CI:
        input("Press Enter to exit...")


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("Telegram send failed:", e)


# =========================================================
# JOHN'S SUPPORT BOUNCE SCANNER (BROKER-FREE VERSION)
# MIDCAP + SMALLCAP
# DAILY
# Data source: Yahoo Finance (no broker/API key needed)
# Stock list: LOCAL CSV FILES (see note below)
# =========================================================

# -----------------------------------------------------------------
# HOW TO GET THE STOCK LIST FILES (one-time, ~2 min, do on your phone):
#   1. Open your browser (not this script) and go to:
#        https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv
#        https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv
#   2. Save each file in the SAME FOLDER as this script, with these
#      exact names:
#        ind_niftymidcap150list.csv
#        ind_niftysmallcap250list.csv
#   3. Re-download these two files every ~6 months (index rebalances
#      happen in Jan/Feb and Jul/Aug). If a download fails or a page
#      won't load, wait a bit and retry from the browser, not this script.
#   Browsers aren't blocked the way scripts are, so this step reliably
#   works even though the automated download inside a script doesn't.
# -----------------------------------------------------------------

LOOKBACK_DAYS = 400  # calendar days of history to pull (needs > 250 trading days for SMA200)
SUPPORT_LOOKBACK = 20
TOP = 15

MIDCAP_FILE = "ind_niftymidcap150list.csv"
SMALLCAP_FILE = "ind_niftysmallcap250list.csv"

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

S = requests.Session()
S.headers.update(HEADERS)


print()
print("JOHN'S SUPPORT BOUNCE SCANNER (BROKER-FREE)")
print("=" * 55)


# =========================================================
# STOCK LIST (from local files)
# =========================================================


def get_list_from_file(path):

    if not os.path.exists(path):
        print(f"Missing file: {path}")
        return []

    try:
        df = pd.read_csv(path)

        for col in df.columns:
            if str(col).lower() == "symbol":
                return df[col].dropna().astype(str).str.strip().tolist()

        print(f"No 'Symbol' column found in {path}")
        return []

    except Exception as e:
        print(f"Error reading {path}: {e}")
        return []


print()
print("Loading Midcap 150 from local file...")
midcap = get_list_from_file(MIDCAP_FILE)
print("Midcap:", len(midcap))

print()
print("Loading Smallcap 250 from local file...")
smallcap = get_list_from_file(SMALLCAP_FILE)
print("Smallcap:", len(smallcap))

stocks = list(dict.fromkeys(midcap + smallcap))

print()
print("Total stocks:", len(stocks))

if not stocks:
    print()
    print("No stocks loaded. Make sure the two CSV files are in the same")
    print("folder as this script (see instructions at the top of the file).")
    send_telegram("⚠️ Support Bounce Scanner: stock list files missing, scan skipped.")
    wait_for_exit()
    raise SystemExit


# =========================================================
# DAILY DATA — YAHOO FINANCE (no broker/API key needed)
# =========================================================


def get_data(symbol):

    yahoo_symbol = symbol.strip().upper() + ".NS"

    end = datetime.now()
    start = end - timedelta(days=LOOKBACK_DAYS)

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"

    params = {"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": "1d", "events": "history"}

    for _attempt in range(3):
        try:
            r = S.get(url, params=params, timeout=15)

            if r.status_code != 200:
                time.sleep(1.5)
                continue

            data = r.json()

            result = data.get("chart", {}).get("result")

            if not result:
                return None

            result = result[0]

            timestamps = result.get("timestamp")

            if not timestamps:
                return None

            quote = result["indicators"]["quote"][0]

            df = pd.DataFrame(
                {
                    "Date": pd.to_datetime(timestamps, unit="s"),
                    "Open": quote.get("open"),
                    "High": quote.get("high"),
                    "Low": quote.get("low"),
                    "Close": quote.get("close"),
                    "Volume": quote.get("volume"),
                }
            )

            df = df.dropna()
            return df.sort_values("Date")

        except Exception:
            time.sleep(1.5)

    return None


# =========================================================
# RSI
# =========================================================


def rsi(series, period=14):

    change = series.diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    return 100 - 100 / (1 + rs)


# =========================================================
# ANALYSE
# =========================================================


def analyse(symbol, df):

    if df is None:
        return None

    if len(df) < 100:
        return None

    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["RSI"] = rsi(df["Close"])
    df["VOL20"] = df["Volume"].rolling(20).mean()

    c = df.iloc[-1]
    p = df.iloc[-2]

    price = float(c["Close"])
    op = float(c["Open"])
    high = float(c["High"])
    low = float(c["Low"])

    sma50 = float(c["SMA50"]) if not pd.isna(c["SMA50"]) else None
    sma200 = float(c["SMA200"]) if not pd.isna(c["SMA200"]) else None

    rv = float(c["RSI"]) if not pd.isna(c["RSI"]) else None

    vol = float(c["Volume"])
    avgvol = float(c["VOL20"]) if not pd.isna(c["VOL20"]) else 0

    if avgvol <= 0:
        return None

    volume_ratio = vol / avgvol

    # -----------------------------------------------------
    # SUPPORT — previous 20 completed days
    # -----------------------------------------------------

    support = float(df["Low"].iloc[-21:-1].min())
    distance = ((price - support) / support) * 100

    if distance > 5:
        return None

    # -----------------------------------------------------
    # BOUNCE DETECTION
    # -----------------------------------------------------

    candle_range = high - low

    if candle_range <= 0:
        return None

    lower_wick = min(op, price) - low
    wick_ratio = lower_wick / candle_range

    bullish = price > op
    improving = price > float(p["Close"])

    if not (bullish or wick_ratio >= 0.30 or improving):
        return None

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

    score = 0
    reasons = []

    if distance <= 2:
        score += 30
        reasons.append("Very close to support")
    else:
        score += 20
        reasons.append("Near support")

    if wick_ratio >= 0.30:
        score += 20
        reasons.append("Support rejection")

    if bullish:
        score += 15
        reasons.append("Bullish candle")

    if improving:
        score += 10
        reasons.append("Price recovering")

    if volume_ratio >= 1.5:
        score += 15
        reasons.append("Volume spike")
    elif volume_ratio >= 1.2:
        score += 8
        reasons.append("Volume increasing")

    if rv is not None and not pd.isna(p["RSI"]) and rv > float(p["RSI"]):
        score += 10
        reasons.append("RSI improving")

    if sma50 is not None and price > sma50:
        score += 5
        reasons.append("Above 50 DMA")

    if sma200 is not None and price > sma200:
        score += 5
        reasons.append("Above 200 DMA")

    # -----------------------------------------------------
    # DONCHIAN
    # -----------------------------------------------------

    donchian_high = float(df["High"].iloc[-21:-1].max())
    distance_to_breakout = ((donchian_high - price) / price) * 100

    # -----------------------------------------------------
    # TRADE PLAN
    # -----------------------------------------------------

    entry = high * 1.002
    stop = support * 0.98
    risk = entry - stop

    if risk <= 0:
        return None

    target1 = entry + risk
    target2 = entry + (risk * 2)
    target3 = entry + (risk * 3)

    return {
        "Stock": symbol,
        "Price": round(price, 2),
        "Support": round(support, 2),
        "SupportGap": round(distance, 2),
        "VolumeX": round(volume_ratio, 2),
        "RSI": round(rv, 1) if rv is not None else None,
        "Score": score,
        "Entry": round(entry, 2),
        "SL": round(stop, 2),
        "T1": round(target1, 2),
        "T2": round(target2, 2),
        "T3": round(target3, 2),
        "Donchian": round(donchian_high, 2),
        "BreakoutGap": round(distance_to_breakout, 2),
        "Reason": ", ".join(reasons),
    }


# =========================================================
# SCAN
# =========================================================

print()
print("=" * 55)
print("STARTING DAILY SUPPORT BOUNCE SCAN")
print("=" * 55)

results = []
failed = 0
total = len(stocks)

for i, symbol in enumerate(stocks, 1):
    print("[" + str(i) + "/" + str(total) + "] " + symbol, end="\r")

    df = get_data(symbol)

    if df is None:
        failed += 1
    else:
        result = analyse(symbol, df)
        if result is not None:
            results.append(result)

    time.sleep(0.4)


# =========================================================
# RESULTS
# =========================================================

print()
print()
print("=" * 55)
print("SCAN FINISHED")
print("=" * 55)

print("Stocks:", total)
print("Failed:", failed)
print("Candidates:", len(results))

if not results:
    print()
    print("No support bounce candidates.")
    send_telegram(f"📊 Support Bounce Scan — {datetime.now().strftime('%d %b %Y')}: no candidates today.")
else:
    df = pd.DataFrame(results)
    df = df.sort_values("Score", ascending=False)
    df.insert(0, "Rank", range(1, len(df) + 1))

    print()
    print("=" * 55)
    print("TOP SUPPORT BOUNCE STOCKS")
    print("=" * 55)

    for i, row in df.head(TOP).iterrows():
        print()
        print("STOCK:", row["Stock"])
        print("PRICE:", row["Price"])
        print("SUPPORT:", row["Support"])
        print("SUPPORT GAP:", row["SupportGap"], "%")
        print("VOLUME:", row["VolumeX"], "X")
        print("RSI:", row["RSI"])
        print("SCORE:", row["Score"])
        print("ENTRY:", row["Entry"])
        print("SL:", row["SL"])
        print("TARGET 1:", row["T1"])
        print("TARGET 2:", row["T2"])
        print("TARGET 3:", row["T3"])
        print("DONCHIAN HIGH:", row["Donchian"])
        print("BREAKOUT GAP:", row["BreakoutGap"], "%")
        print("REASON:", row["Reason"])
        print("-" * 55)

    filename = "support_bounce_" + datetime.now().strftime("%Y%m%d_%H%M") + ".csv"
    df.to_csv(filename, index=False)

    print()
    print("Saved:", filename)

    top5 = df.head(5)
    lines = [f"📊 <b>Support Bounce Scan — {datetime.now().strftime('%d %b %Y')}</b>"]
    lines.append(f"Candidates: {len(df)} / {total} scanned\n")
    for _, row in top5.iterrows():
        lines.append(
            f"#{int(row['Rank'])} {row['Stock']} | Score {row['Score']} | "
            f"₹{row['Price']} | Entry {row['Entry']} | SL {row['SL']}"
        )
    send_telegram("\n".join(lines))

print()
print("=" * 55)
print("JOHN'S SCANNER COMPLETE")
print("=" * 55)

wait_for_exit()
