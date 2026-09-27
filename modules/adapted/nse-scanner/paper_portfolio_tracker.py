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


import glob
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

# =========================================================
# PAPER PORTFOLIO TRACKER — SUPPORT BOUNCE SCANNER
# Runs right after support_bounce_scanner_free.py each day.
#
# Logic:
#   1. Any PENDING position from yesterday gets its actual
#      entry price filled in using TODAY's open (simulates
#      an AMO placed yesterday, executed at today's open).
#   2. Every OPEN position is checked against SL / T1 / T2 / T3
#      using price history since its entry date. First hit wins.
#      If nothing hit within 14 calendar days, closes at the
#      most recent close (TIME_EXIT).
#   3. Today's scan's top 10 (by Rank) get added as new PENDING
#      positions, to be filled at tomorrow's open on the next run.
# =========================================================

HOLD_DAYS = 14
TOP_N = 10

PORTFOLIO_FILE = "paper_portfolio.csv"

RUNNING_IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
S = requests.Session()
S.headers.update(HEADERS)


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
# PRICE DATA — YAHOO FINANCE
# =========================================================


def get_price_history(symbol, start_date, end_date):

    yahoo_symbol = symbol.strip().upper() + ".NS"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"

    params = {
        "period1": int(start_date.timestamp()),
        "period2": int(end_date.timestamp()),
        "interval": "1d",
        "events": "history",
    }

    try:
        r = S.get(url, params=params, timeout=15)

        if r.status_code != 200:
            return None

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
                "Date": pd.to_datetime(timestamps, unit="s").date,
                "Open": quote.get("open"),
                "High": quote.get("high"),
                "Low": quote.get("low"),
                "Close": quote.get("close"),
            }
        )

        df = df.dropna()
        return df.sort_values("Date")

    except Exception:
        return None


# =========================================================
# LOAD LATEST SCAN RESULT
# =========================================================


def get_latest_scan_file():

    files = glob.glob("support_bounce_*.csv")

    # exclude the portfolio file itself if it ever matches the glob
    files = [f for f in files if "portfolio" not in f]

    if not files:
        return None

    files.sort(reverse=True)

    return files[0]


# =========================================================
# LOAD / INIT PORTFOLIO
# =========================================================

COLUMNS = [
    "EntryID",
    "Stock",
    "ScanDate",
    "RankOnScanDay",
    "PlannedEntry",
    "SL",
    "T1",
    "T2",
    "T3",
    "Qty",
    "Status",
    "ActualEntryDate",
    "ActualEntryPrice",
    "ExitDate",
    "ExitPrice",
    "ExitReason",
    "ReturnPct",
    "PnL",
]


def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        df = pd.read_csv(PORTFOLIO_FILE)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = np.nan
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


# =========================================================
# MAIN
# =========================================================

print()
print("PAPER PORTFOLIO TRACKER")
print("=" * 55)

today = datetime.now().date()

portfolio = load_portfolio()

print("Existing positions loaded:", len(portfolio))

# ---------------------------------------------------------
# STEP 1: fill entry price for PENDING positions using
# today's open (yesterday's AMO executes today)
# ---------------------------------------------------------

pending_mask = portfolio["Status"] == "PENDING"
pending_idx = portfolio[pending_mask].index

for idx in pending_idx:
    stock = portfolio.at[idx, "Stock"]

    hist = get_price_history(stock, datetime.now() - timedelta(days=5), datetime.now() + timedelta(days=1))

    if hist is None or hist.empty:
        continue

    today_rows = hist[hist["Date"] == today]

    if today_rows.empty:
        # market may not have opened yet / holiday — leave PENDING
        continue

    open_price = float(today_rows.iloc[0]["Open"])

    portfolio.at[idx, "Status"] = "OPEN"
    portfolio.at[idx, "ActualEntryDate"] = str(today)
    portfolio.at[idx, "ActualEntryPrice"] = round(open_price, 2)

print("Positions activated today:", len(pending_idx))

# ---------------------------------------------------------
# STEP 2: check OPEN positions against SL / targets / time exit
# ---------------------------------------------------------

open_idx = portfolio[portfolio["Status"] == "OPEN"].index
closed_today = 0

for idx in open_idx:
    stock = portfolio.at[idx, "Stock"]
    entry_date = pd.to_datetime(portfolio.at[idx, "ActualEntryDate"]).date()
    entry_price = float(portfolio.at[idx, "ActualEntryPrice"])
    sl = float(portfolio.at[idx, "SL"])
    t1 = float(portfolio.at[idx, "T1"])
    t2 = float(portfolio.at[idx, "T2"])
    t3 = float(portfolio.at[idx, "T3"])

    hist = get_price_history(
        stock, datetime.combine(entry_date, datetime.min.time()), datetime.now() + timedelta(days=1)
    )

    if hist is None or hist.empty:
        continue

    hist = hist[hist["Date"] >= entry_date]

    exit_price = None
    exit_reason = None
    exit_date = None

    for _, row in hist.iterrows():
        low = float(row["Low"])
        high = float(row["High"])

        if low <= sl:
            exit_price = sl
            exit_reason = "SL_HIT"
            exit_date = row["Date"]
            break

        if high >= t3:
            exit_price = t3
            exit_reason = "T3_HIT"
            exit_date = row["Date"]
            break

        if high >= t2:
            exit_price = t2
            exit_reason = "T2_HIT"
            exit_date = row["Date"]
            break

        if high >= t1:
            exit_price = t1
            exit_reason = "T1_HIT"
            exit_date = row["Date"]
            break

    if exit_price is None:
        # nothing hit yet — check time exit
        days_held = (today - entry_date).days

        if days_held >= HOLD_DAYS:
            exit_price = float(hist.iloc[-1]["Close"])
            exit_reason = "TIME_EXIT"
            exit_date = hist.iloc[-1]["Date"]

    if exit_price is not None:
        ret_pct = ((exit_price - entry_price) / entry_price) * 100

        portfolio.at[idx, "Status"] = "CLOSED"
        portfolio.at[idx, "ExitDate"] = str(exit_date)
        portfolio.at[idx, "ExitPrice"] = round(exit_price, 2)
        portfolio.at[idx, "ExitReason"] = exit_reason
        portfolio.at[idx, "ReturnPct"] = round(ret_pct, 2)
        portfolio.at[idx, "PnL"] = round(exit_price - entry_price, 2)  # 1 share

        closed_today += 1

print("Positions closed today:", closed_today)

# ---------------------------------------------------------
# STEP 3: add today's top 10 as new PENDING positions
# ---------------------------------------------------------

scan_file = get_latest_scan_file()
new_entries = 0

if scan_file is None:
    print("No scan file found — skipping new entries.")
else:
    print("Reading today's scan from:", scan_file)

    scan_df = pd.read_csv(scan_file)

    if "Rank" in scan_df.columns:
        top10 = scan_df.sort_values("Rank").head(TOP_N)
    else:
        top10 = scan_df.sort_values("Score", ascending=False).head(TOP_N)

    scan_date_str = str(today)

    next_id = 1
    if not portfolio.empty and portfolio["EntryID"].notna().any():
        next_id = int(portfolio["EntryID"].max()) + 1

    new_rows = []

    for _, row in top10.iterrows():
        new_rows.append(
            {
                "EntryID": next_id,
                "Stock": row["Stock"],
                "ScanDate": scan_date_str,
                "RankOnScanDay": row.get("Rank", None),
                "PlannedEntry": row["Entry"],
                "SL": row["SL"],
                "T1": row["T1"],
                "T2": row["T2"],
                "T3": row["T3"],
                "Qty": 1,
                "Status": "PENDING",
                "ActualEntryDate": None,
                "ActualEntryPrice": None,
                "ExitDate": None,
                "ExitPrice": None,
                "ExitReason": None,
                "ReturnPct": None,
                "PnL": None,
            }
        )

        next_id += 1

    if new_rows:
        portfolio = pd.concat([portfolio, pd.DataFrame(new_rows)], ignore_index=True)
        new_entries = len(new_rows)

print("New paper entries added:", new_entries)

# ---------------------------------------------------------
# SAVE
# ---------------------------------------------------------

portfolio.to_csv(PORTFOLIO_FILE, index=False)
print()
print("Saved:", PORTFOLIO_FILE)

# ---------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------

closed = portfolio[portfolio["Status"] == "CLOSED"]
open_pos = portfolio[portfolio["Status"] == "OPEN"]
pending_pos = portfolio[portfolio["Status"] == "PENDING"]

total_closed = len(closed)
wins = len(closed[closed["ReturnPct"] > 0])
win_rate = round((wins / total_closed) * 100, 1) if total_closed > 0 else 0
avg_return = round(closed["ReturnPct"].mean(), 2) if total_closed > 0 else 0
total_pnl = round(closed["PnL"].sum(), 2) if total_closed > 0 else 0

print()
print("=" * 55)
print("PORTFOLIO SUMMARY")
print("=" * 55)
print("Open positions:", len(open_pos))
print("Pending (AMO not yet filled):", len(pending_pos))
print("Closed positions:", total_closed)
print("Win rate:", win_rate, "%")
print("Avg return per closed trade:", avg_return, "%")
print("Total P&L (₹, 1 share each):", total_pnl)

lines = [f"📈 <b>Paper Portfolio Update — {today.strftime('%d %b %Y')}</b>"]
lines.append(f"Open: {len(open_pos)} | Pending: {len(pending_pos)} | Closed: {total_closed}")
lines.append(f"Win rate: {win_rate}% | Avg return: {avg_return}% | Total P&L: ₹{total_pnl}")

if closed_today > 0:
    lines.append("")
    lines.append("<b>Closed today:</b>")
    todays_closed = closed[closed["ExitDate"] == str(today)]
    for _, row in todays_closed.iterrows():
        lines.append(f"{row['Stock']}: {row['ExitReason']} ({row['ReturnPct']}%)")

send_telegram("\n".join(lines))

print()
print("=" * 55)
print("TRACKER COMPLETE")
print("=" * 55)

wait_for_exit()
