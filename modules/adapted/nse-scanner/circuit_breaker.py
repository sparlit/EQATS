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
Circuit Breaker - Daily Price Crash Monitor
Runs daily via GitHub Actions. Checks each holding for sudden price crashes
that warrant immediate manual review, rather than waiting for the quarterly
fundamental re-screen cycle.

Sends alerts via Telegram bot (reuses the same bot pattern as your
Nifty-scanner repo).
"""

import os
from datetime import timedelta

import pandas as pd
import requests

# ---------------- CONFIG ----------------
PORTFOLIO_FILE = "portfolio_holdings.csv"
PRICE_HISTORY_FILE = "price_history.csv"  # tracks daily closes for drop detection

DAILY_DROP_ALERT_PCT = 8.0  # alert if single-day drop exceeds this
WEEKLY_DROP_ALERT_PCT = 15.0  # alert if 5-trading-day drop exceeds this
FROM_HIGH_ALERT_PCT = 25.0  # alert if down this much from 52-week high

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ---------------- DATA FETCH ----------------
def fetch_yahoo_data(symbol, range_period="1y", interval="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_period, "interval": interval}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        result = data["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {"date": pd.to_datetime(ts, unit="s").normalize(), "close": q["close"], "high": q["high"], "low": q["low"]}
        )
        df = df.dropna()
        return df.set_index("date")
    except Exception as e:
        print(f"  fetch failed {symbol}: {e}")
        return None


# ---------------- TELEGRAM ----------------
def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set - skipping alert send.")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram send failed: {e}")


# ---------------- MAIN ----------------
def run_circuit_breaker():
    try:
        portfolio_df = pd.read_csv(PORTFOLIO_FILE)
    except FileNotFoundError:
        print("No portfolio file found. Run quality_holdings.py first.")
        return

    holdings = portfolio_df[portfolio_df["status"] == "HOLD"]
    if holdings.empty:
        print("No active holdings to monitor.")
        return

    alerts = []
    summary_lines = []

    for _, pos in holdings.iterrows():
        sym = pos["symbol"]
        yahoo_sym = f"{sym}.NS"
        df = fetch_yahoo_data(yahoo_sym)
        if df is None or len(df) < 6:
            continue

        latest_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        week_ago_close = df["close"].iloc[-6] if len(df) >= 6 else df["close"].iloc[0]
        year_high = df["high"].max()

        daily_change_pct = (latest_close - prev_close) / prev_close * 100
        weekly_change_pct = (latest_close - week_ago_close) / week_ago_close * 100
        from_high_pct = (latest_close - year_high) / year_high * 100

        summary_lines.append(
            f"{sym:12s} LTP:{latest_close:>8.1f}  1D:{daily_change_pct:>+6.1f}%  "
            f"5D:{weekly_change_pct:>+6.1f}%  FromHigh:{from_high_pct:>+6.1f}%"
        )

        reasons = []
        if daily_change_pct <= -DAILY_DROP_ALERT_PCT:
            reasons.append(f"Single-day drop of {daily_change_pct:.1f}%")
        if weekly_change_pct <= -WEEKLY_DROP_ALERT_PCT:
            reasons.append(f"5-day drop of {weekly_change_pct:.1f}%")
        if from_high_pct <= -FROM_HIGH_ALERT_PCT:
            reasons.append(f"Down {abs(from_high_pct):.1f}% from 52-week high")

        if reasons:
            alerts.append((sym, latest_close, reasons))

    print("=" * 60)
    print("DAILY PRICE MONITOR - ALL HOLDINGS")
    print("=" * 60)
    for line in summary_lines:
        print(line)

    if alerts:
        msg_lines = ["<b>⚠️ CIRCUIT BREAKER ALERT</b>", ""]
        msg_lines.append("Sudden price move detected - review before next quarterly screen:")
        msg_lines.append("")
        for sym, price, reasons in alerts:
            msg_lines.append(f"<b>{sym}</b> (LTP: {price:.1f})")
            for r in reasons:
                msg_lines.append(f"  • {r}")
            msg_lines.append("")
        msg_lines.append("Check news/announcements before deciding to hold or exit.")
        message = "\n".join(msg_lines)

        print("\n" + "=" * 60)
        print("ALERTS TRIGGERED")
        print("=" * 60)
        print(message)

        send_telegram_alert(message)
    else:
        print("\nNo circuit breaker alerts today. All holdings within normal range.")
        quiet_msg = f"✅ Daily check: all {len(holdings)} holdings stable. No action needed."
        send_telegram_alert(quiet_msg)


if __name__ == "__main__":
    run_circuit_breaker()
