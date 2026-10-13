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
import time
from datetime import datetime

import pandas as pd
import requests

os.makedirs("data", exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BREAKOUT_TARGET_RATIO = 1.5
TOP_N = 5
ENTRY_FILE = "data/monthlylevels_paper_entries.csv"
LOG_FILE = "data/monthlylevels_paper_log.csv"
CLOSED_FILE = "data/monthlylevels_paper_closed.csv"
SUMMARY_FILE = "data/monthlylevels_portfolio_summary.csv"

STOCK_LIST = [
    "HDFCBANK.NS",
    "SBIN.NS",
    "PERSISTENT.NS",
    "COFORGE.NS",
    "ASHOKLEY.NS",
    "M&M.NS",
    "BEL.NS",
    "COALINDIA.NS",
    "TATAMOTORS.NS",
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "AXISBANK.NS",
    "KOTAKBANK.NS",
    "LT.NS",
    "BAJFINANCE.NS",
    "BAJAJFINSV.NS",
    "MARUTI.NS",
    "TITAN.NS",
    "SUNPHARMA.NS",
    "DRREDDY.NS",
    "CIPLA.NS",
    "DIVISLAB.NS",
    "NTPC.NS",
    "POWERGRID.NS",
    "ONGC.NS",
    "BPCL.NS",
    "IOC.NS",
    "HINDALCO.NS",
    "JSWSTEEL.NS",
    "TATASTEEL.NS",
    "ADANIPORTS.NS",
    "ADANIENT.NS",
    "ULTRACEMCO.NS",
    "GRASIM.NS",
    "NESTLEIND.NS",
    "BRITANNIA.NS",
    "ITC.NS",
    "HINDUNILVR.NS",
    "ASIANPAINT.NS",
    "WIPRO.NS",
    "HCLTECH.NS",
    "TECHM.NS",
    "LTIM.NS",
    "BHARTIARTL.NS",
    "INDUSINDBK.NS",
    "BAJAJ-AUTO.NS",
    "EICHERMOT.NS",
    "HEROMOTOCO.NS",
    "DLF.NS",
    "GODREJPROP.NS",
    "SIEMENS.NS",
    "ABB.NS",
    "CUMMINSIND.NS",
    "HAL.NS",
    "BEML.NS",
    "BHEL.NS",
    "IRCTC.NS",
    "IRFC.NS",
    "ZOMATO.NS",
    "TRENT.NS",
    "VEDL.NS",
    "SAIL.NS",
]


def fetch_monthly_data(symbol, retries=2):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1y", "interval": "1mo"}
    for _attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            data = r.json()
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame(
                {"High": q["high"], "Low": q["low"], "Close": q["close"]},
                index=pd.to_datetime(ts, unit="s"),
            )
            df = df.dropna()
            if len(df) < 2:
                return None
            return df
        except Exception:
            time.sleep(1)
    return None


def fetch_daily_data(symbol, retries=2):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "3mo", "interval": "1d"}
    for _attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            data = r.json()
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame(
                {"High": q["high"], "Low": q["low"], "Close": q["close"]},
                index=pd.to_datetime(ts, unit="s"),
            )
            df = df.dropna()
            if len(df) < 3:
                return None
            return df
        except Exception:
            time.sleep(1)
    return None


def get_current_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1d", "interval": "1m"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        return round(float(data["chart"]["result"][0]["meta"]["regularMarketPrice"]), 2)
    except Exception:
        return None


def analyze(symbol, monthly_df, daily_df):
    prev_month = monthly_df.iloc[-2]
    level_0 = float(prev_month["Low"])
    level_1 = float(prev_month["High"])
    distance = level_1 - level_0
    level_032 = round(level_0 + 0.32 * distance, 2)
    level_068 = round(level_0 + 0.68 * distance, 2)
    today = daily_df.index[-1]
    month_start = pd.Timestamp(year=today.year, month=today.month, day=1)
    current_month_df = daily_df[daily_df.index >= month_start]
    if current_month_df.empty:
        return None
    today_close = float(current_month_df["Close"].iloc[-1])
    month_min_low = float(current_month_df["Low"].min())
    month_max_high = float(current_month_df["High"].max())
    swept_below_low = month_min_low < level_0
    swept_above_high = month_max_high > level_1
    reversal_buy = swept_below_low and today_close > level_032
    reversal_sell = swept_above_high and today_close < level_068
    breakout_buy = today_close > level_1
    breakout_sell = today_close < level_0
    if reversal_buy:
        signal = "REVERSAL BUY"
        entry = today_close
        target = level_068
        stop_loss = level_0
    elif breakout_buy:
        signal = "BREAKOUT BUY"
        entry = today_close
        stop_loss = level_068
        risk = entry - stop_loss
        target = round(entry + risk * BREAKOUT_TARGET_RATIO, 2)
    elif reversal_sell:
        signal = "AVOID (Reversal Sell)"
        entry = None
        target = level_032
        stop_loss = level_1
    elif breakout_sell:
        signal = "AVOID (Breakout Sell)"
        entry = None
        target = None
        stop_loss = level_032
    else:
        signal = "NEUTRAL"
        entry = None
        target = None
        stop_loss = None
    return {
        "Symbol": symbol.replace(".NS", ""),
        "Date": today.strftime("%Y-%m-%d"),
        "CMP": round(today_close, 2),
        "MonthlyLow": round(level_0, 2),
        "BuyZone032": level_032,
        "SellZone068": level_068,
        "MonthlyHigh": round(level_1, 2),
        "Signal": signal,
        "Entry": entry,
        "Target": target,
        "StopLoss": stop_loss,
    }


def run_scan():
    results = []
    for i, sym in enumerate(STOCK_LIST, 1):
        print(f"[{i}/{len(STOCK_LIST)}] Scanning {sym} ...")
        monthly_df = fetch_monthly_data(sym)
        daily_df = fetch_daily_data(sym)
        if monthly_df is None or daily_df is None:
            continue
        try:
            res = analyze(sym, monthly_df, daily_df)
            if res:
                results.append(res)
        except Exception as e:
            print(f"  skip {sym}: {e}")
        time.sleep(0.4)
    dfres = pd.DataFrame(results)
    if dfres.empty:
        print("No data fetched.")
        return None
    buy_signals = dfres[dfres["Signal"].isin(["REVERSAL BUY", "BREAKOUT BUY"])]
    dfres.to_csv("data/monthlylevels_full.csv", index=False)
    buy_signals.to_csv("data/monthlylevels_buy.csv", index=False)
    print(f"BUY signals: {len(buy_signals)}")
    return buy_signals


def manage_positions(buy_signals):
    if os.path.exists(ENTRY_FILE):
        entries = pd.read_csv(ENTRY_FILE)
    else:
        entries = pd.DataFrame(
            columns=["Symbol", "EntryDate", "Signal", "BuyPrice", "Target", "StopLoss"]
        )

    today_rows = []
    keep_rows = []

    print(f"\n=== Checking {len(entries)} existing positions ===")
    for _, row in entries.iterrows():
        cur_price = get_current_price(row["Symbol"] + ".NS")
        if cur_price is None:
            keep_rows.append(row.to_dict())
            continue
        pnl_pct = round((cur_price - row["BuyPrice"]) / row["BuyPrice"] * 100, 2)
        status = "HOLDING"
        if cur_price >= row["Target"]:
            status = "TARGET HIT"
        elif cur_price <= row["StopLoss"]:
            status = "SL HIT"
        today_rows.append(
            {
                "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Symbol": row["Symbol"],
                "Signal": row.get("Signal", ""),
                "BuyPrice": row["BuyPrice"],
                "CurrentPrice": cur_price,
                "Target": row["Target"],
                "StopLoss": row["StopLoss"],
                "PnL%": pnl_pct,
                "Status": status,
            }
        )
        print(
            f"{row['Symbol']:12s} Buy:{row['BuyPrice']:>9.2f} Now:{cur_price:>9.2f} P&L:{pnl_pct:>6.2f}% [{status}]"
        )
        if status == "HOLDING":
            keep_rows.append(row.to_dict())

    closed_today = [r for r in today_rows if r["Status"] != "HOLDING"]
    if closed_today:
        closed_df = pd.DataFrame(closed_today)
        symbols_closed = closed_df["Symbol"].tolist()
        print(f"\nClosed positions (hit Target/SL): {symbols_closed}")
        if os.path.exists(CLOSED_FILE):
            closed_df.to_csv(CLOSED_FILE, mode="a", header=False, index=False)
        else:
            closed_df.to_csv(CLOSED_FILE, index=False)

    held_symbols = {r["Symbol"] for r in keep_rows}
    slots_needed = TOP_N - len(keep_rows)
    new_entries = []
    if slots_needed > 0 and buy_signals is not None and not buy_signals.empty:
        candidates_pool = (
            buy_signals[~buy_signals["Symbol"].isin(held_symbols)]
            .dropna(subset=["Entry", "Target", "StopLoss"])
            .head(slots_needed)
        )
        for _, r in candidates_pool.iterrows():
            new_entries.append(
                {
                    "Symbol": r["Symbol"],
                    "EntryDate": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Signal": r["Signal"],
                    "BuyPrice": r["Entry"],
                    "Target": r["Target"],
                    "StopLoss": r["StopLoss"],
                }
            )
            today_rows.append(
                {
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Symbol": r["Symbol"],
                    "Signal": r["Signal"],
                    "BuyPrice": r["Entry"],
                    "CurrentPrice": r["Entry"],
                    "Target": r["Target"],
                    "StopLoss": r["StopLoss"],
                    "PnL%": 0.0,
                    "Status": "HOLDING",
                }
            )
            print(f"  NEW ENTRY: {r['Symbol']} @ {r['Entry']} (replacing closed slot)")

    final_entries = pd.DataFrame(keep_rows + new_entries)
    final_entries.to_csv(ENTRY_FILE, index=False)

    log_df = pd.DataFrame(today_rows)
    if not log_df.empty:
        if os.path.exists(LOG_FILE):
            log_df.to_csv(LOG_FILE, mode="a", header=False, index=False)
        else:
            log_df.to_csv(LOG_FILE, index=False)

    open_rows = log_df[log_df["Status"] == "HOLDING"] if not log_df.empty else pd.DataFrame()
    total_invested = open_rows["BuyPrice"].sum() if not open_rows.empty else 0
    total_current_value = open_rows["CurrentPrice"].sum() if not open_rows.empty else 0
    overall_pnl_pct = (
        round((total_current_value - total_invested) / total_invested * 100, 2)
        if total_invested > 0
        else 0
    )

    print("\n=== MONTHLY LEVELS PORTFOLIO SUMMARY ===")
    print(
        f"Total Entry Value: {total_invested:.2f} | Current Value: {total_current_value:.2f} | Overall P&L: {overall_pnl_pct}%"
    )

    summary_row = pd.DataFrame(
        [
            {
                "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "TotalEntryValue": round(total_invested, 2),
                "TotalCurrentValue": round(total_current_value, 2),
                "OverallPnL%": overall_pnl_pct,
                "StocksHolding": len(open_rows),
                "StocksTargetHitToday": len(
                    [r for r in closed_today if r["Status"] == "TARGET HIT"]
                ),
                "StocksSLHitToday": len([r for r in closed_today if r["Status"] == "SL HIT"]),
            }
        ]
    )
    if os.path.exists(SUMMARY_FILE):
        summary_row.to_csv(SUMMARY_FILE, mode="a", header=False, index=False)
    else:
        summary_row.to_csv(SUMMARY_FILE, index=False)


if __name__ == "__main__":
    print("=== MONTHLY LEVELS SCANNER ===")
    buy_signals = run_scan()
    manage_positions(buy_signals)
