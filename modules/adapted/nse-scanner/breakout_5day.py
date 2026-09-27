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
TRIGGER_PCT = 0.24
REWARD_RISK_RATIO = 2
TOP_N = 5
ENTRY_FILE = "data/breakout5d_paper_entries.csv"
LOG_FILE = "data/breakout5d_paper_log.csv"
CLOSED_FILE = "data/breakout5d_paper_closed.csv"
SUMMARY_FILE = "data/breakout5d_portfolio_summary.csv"

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


def fetch_data(symbol, retries=2):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "2mo", "interval": "1d"}
    for _attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            data = r.json()
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame(
                {"Open": q["open"], "High": q["high"], "Low": q["low"], "Close": q["close"], "Volume": q["volume"]},
                index=pd.to_datetime(ts, unit="s"),
            )
            df = df.dropna()
            if len(df) < 20:
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


def check_circuit_pattern(df, lookback_days=22):
    close = df["Close"]
    today_close = float(close.iloc[-1])
    recent = df.tail(lookback_days).copy()
    recent["PrevClose"] = recent["Close"].shift(1)
    recent["Move%"] = (recent["Close"] - recent["PrevClose"]) / recent["PrevClose"] * 100
    recent["DayRange%"] = (recent["High"] - recent["Low"]) / recent["Low"] * 100
    recent["LikelyCircuitDay"] = (recent["Move%"].abs() >= 8.0) & (recent["DayRange%"] < 1.0)
    upper_circuit_days = recent[recent["LikelyCircuitDay"] & (recent["Move%"] > 0)]
    reversed_from_upper = False
    if not upper_circuit_days.empty:
        last_upper_close = float(upper_circuit_days["Close"].iloc[-1])
        reversed_from_upper = today_close < last_upper_close * 0.98
    return {"CircuitSignal": "AVOID" if reversed_from_upper else "NEUTRAL"}


def analyze(symbol, df):
    recent5 = df.iloc[-6:-1]
    today_close = float(df["Close"].iloc[-1])
    today_date = df.index[-1]
    high_avg = float(recent5["High"].mean())
    low_avg = float(recent5["Low"].mean())
    distance = high_avg - low_avg
    midpoint = (high_avg + low_avg) / 2
    upper_trigger = midpoint + TRIGGER_PCT * distance
    lower_trigger = midpoint - TRIGGER_PCT * distance
    if today_close > upper_trigger:
        signal = "BUY"
        breakout_pct = round((today_close - upper_trigger) / upper_trigger * 100, 2)
    elif today_close < lower_trigger:
        signal = "SELL"
        breakout_pct = round((lower_trigger - today_close) / lower_trigger * 100, 2)
    else:
        signal = "NEUTRAL"
        breakout_pct = 0.0
    stop_loss = round(midpoint, 2)
    risk = today_close - stop_loss
    target = round(today_close + (risk * REWARD_RISK_RATIO), 2)
    circuit_info = check_circuit_pattern(df)
    return {
        "Symbol": symbol.replace(".NS", ""),
        "Date": today_date.strftime("%Y-%m-%d"),
        "CMP": round(today_close, 2),
        "Signal": signal,
        "BreakoutStrength%": breakout_pct,
        "Target": target,
        "StopLoss(Midpoint)": stop_loss,
        **circuit_info,
    }


def run_scan():
    results = []
    for i, sym in enumerate(STOCK_LIST, 1):
        print(f"[{i}/{len(STOCK_LIST)}] Scanning {sym} ...")
        df = fetch_data(sym)
        if df is None:
            continue
        try:
            results.append(analyze(sym, df))
        except Exception as e:
            print(f"  skip {sym}: {e}")
        time.sleep(0.4)
    dfres = pd.DataFrame(results)
    if dfres.empty:
        print("No data fetched.")
        return None
    buy_signals = dfres[(dfres["Signal"] == "BUY") & (dfres["CircuitSignal"] != "AVOID")].sort_values(
        "BreakoutStrength%", ascending=False
    )
    dfres.to_csv("data/breakout5d_full.csv", index=False)
    buy_signals.to_csv("data/breakout5d_buy.csv", index=False)
    print(f"BUY signals: {len(buy_signals)}")
    return buy_signals


def manage_positions(buy_signals):
    if os.path.exists(ENTRY_FILE):
        entries = pd.read_csv(ENTRY_FILE)
    else:
        entries = pd.DataFrame(columns=["Symbol", "EntryDate", "BuyPrice", "Target", "StopLoss"])

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
                "BuyPrice": row["BuyPrice"],
                "CurrentPrice": cur_price,
                "Target": row["Target"],
                "StopLoss": row["StopLoss"],
                "PnL%": pnl_pct,
                "Status": status,
            }
        )
        print(f"{row['Symbol']:12s} Buy:{row['BuyPrice']:>9.2f} Now:{cur_price:>9.2f} P&L:{pnl_pct:>6.2f}% [{status}]")
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
        candidates = (
            buy_signals[~buy_signals["Symbol"].isin(held_symbols)]
            .sort_values("BreakoutStrength%", ascending=False)
            .head(slots_needed)
        )
        for _, r in candidates.iterrows():
            new_entries.append(
                {
                    "Symbol": r["Symbol"],
                    "EntryDate": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "BuyPrice": r["CMP"],
                    "Target": r["Target"],
                    "StopLoss": r["StopLoss(Midpoint)"],
                }
            )
            today_rows.append(
                {
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Symbol": r["Symbol"],
                    "BuyPrice": r["CMP"],
                    "CurrentPrice": r["CMP"],
                    "Target": r["Target"],
                    "StopLoss": r["StopLoss(Midpoint)"],
                    "PnL%": 0.0,
                    "Status": "HOLDING",
                }
            )
            print(f"  NEW ENTRY: {r['Symbol']} @ {r['CMP']} (replacing closed slot)")

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
        round((total_current_value - total_invested) / total_invested * 100, 2) if total_invested > 0 else 0
    )

    print("\n=== 5D BREAKOUT PORTFOLIO SUMMARY ===")
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
                "StocksTargetHitToday": len([r for r in closed_today if r["Status"] == "TARGET HIT"]),
                "StocksSLHitToday": len([r for r in closed_today if r["Status"] == "SL HIT"]),
            }
        ]
    )
    if os.path.exists(SUMMARY_FILE):
        summary_row.to_csv(SUMMARY_FILE, mode="a", header=False, index=False)
    else:
        summary_row.to_csv(SUMMARY_FILE, index=False)


if __name__ == "__main__":
    print("=== 5D BREAKOUT SCANNER ===")
    buy_signals = run_scan()
    manage_positions(buy_signals)
