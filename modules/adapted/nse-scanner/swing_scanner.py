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


import math
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd
import requests

os.makedirs("data", exist_ok=True)

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
    "PIDILITIND.NS",
    "DABUR.NS",
    "MARICO.NS",
    "COLPAL.NS",
    "APOLLOHOSP.NS",
    "MAXHEALTH.NS",
    "LUPIN.NS",
    "AUROPHARMA.NS",
    "BIOCON.NS",
    "VEDL.NS",
    "SAIL.NS",
    "NMDC.NS",
    "JINDALSTEL.NS",
    "CANBK.NS",
    "PNB.NS",
    "BANKBARODA.NS",
    "IDFCFIRSTB.NS",
    "FEDERALBNK.NS",
    "AUBANK.NS",
    "MUTHOOTFIN.NS",
    "CHOLAFIN.NS",
    "SHRIRAMFIN.NS",
    "LICI.NS",
    "SBILIFE.NS",
    "HDFCLIFE.NS",
    "ICICIPRULI.NS",
    "PFC.NS",
    "RECLTD.NS",
    "GAIL.NS",
    "IGL.NS",
    "MGL.NS",
    "TATAPOWER.NS",
    "ADANIGREEN.NS",
]

MIN_SCORE = 4
MIN_PROFIT_PCT = 10
TOP_N = 5

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

ENTRY_FILE = "data/swing_paper_entries.csv"
LOG_FILE = "data/swing_paper_log.csv"
CLOSED_FILE = "data/swing_paper_closed.csv"
SUMMARY_FILE = "data/swing_portfolio_summary.csv"


def fetch_data(symbol, retries=2):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1y", "interval": "1d"}
    for _attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            data = r.json()
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame(
                {
                    "Open": q["open"],
                    "High": q["high"],
                    "Low": q["low"],
                    "Close": q["close"],
                    "Volume": q["volume"],
                },
                index=pd.to_datetime(ts, unit="s"),
            )
            df = df.dropna()
            if len(df) < 210:
                return None
            return df
        except Exception:
            time.sleep(1)
    return None


def wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def hma(series, period):
    half = max(int(period / 2), 1)
    sqrt_p = max(int(round(math.sqrt(period))), 1)
    wma_half = wma(series, half)
    wma_full = wma(series, period)
    diff = 2 * wma_half - wma_full
    return wma(diff, sqrt_p)


def gann_levels(price, spread=2):
    root = math.sqrt(price)
    base = math.floor(root)
    increments = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]
    levels = set()
    for b in range(base - spread, base + spread + 1):
        for inc in increments:
            v = (b + inc) ** 2
            if v > 0:
                levels.add(round(v, 2))
    return sorted(levels)


def resistance_levels(high, latest, lookback=60, window=5):
    h = high.tail(lookback)
    peaks = []
    vals = h.values
    for i in range(window, len(vals) - window):
        segment = vals[i - window : i + window + 1]
        if vals[i] == segment.max():
            peaks.append(round(float(vals[i]), 2))
    peaks = sorted(set(peaks))
    below = [p for p in peaks if p <= latest * 1.02]
    above = [p for p in peaks if p > latest * 1.02]
    return below, above


def check_circuit_pattern(df, lookback_days=22):
    close = df["Close"]
    today_close = float(close.iloc[-1])
    recent = df.tail(lookback_days).copy()
    recent["PrevClose"] = recent["Close"].shift(1)
    recent["Move%"] = (recent["Close"] - recent["PrevClose"]) / recent["PrevClose"] * 100
    recent["DayRange%"] = (recent["High"] - recent["Low"]) / recent["Low"] * 100
    recent["LikelyCircuitDay"] = (recent["Move%"].abs() >= 8.0) & (recent["DayRange%"] < 1.0)
    lower_circuit_days = recent[recent["LikelyCircuitDay"] & (recent["Move%"] < 0)]
    upper_circuit_days = recent[recent["LikelyCircuitDay"] & (recent["Move%"] > 0)]
    touched_lower = not lower_circuit_days.empty
    touched_upper = not upper_circuit_days.empty
    bounced_from_lower = False
    if touched_lower:
        last_lower_close = float(lower_circuit_days["Close"].iloc[-1])
        bounced_from_lower = today_close > last_lower_close * 1.02
    reversed_from_upper = False
    if touched_upper:
        last_upper_close = float(upper_circuit_days["Close"].iloc[-1])
        reversed_from_upper = today_close < last_upper_close * 0.98
    if reversed_from_upper:
        circuit_signal = "AVOID"
    elif bounced_from_lower:
        circuit_signal = "FAVORABLE"
    else:
        circuit_signal = "NEUTRAL"
    return {"CircuitSignal": circuit_signal}


def analyze(symbol, df):
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    latest = float(close.iloc[-1])
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    hma21 = hma(close, 21)
    uptrend = latest > ema50.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1]
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    cross = (macd > signal) & (macd.shift(1) <= signal.shift(1))
    reversed_recent = bool(cross.tail(5).any())
    above_hma = latest > hma21.iloc[-1]
    hma_buy = hma21.iloc[-1] > hma21.iloc[-2] > hma21.iloc[-3]
    hma_condition = bool(above_hma and hma_buy)
    high_52w = float(high.tail(252).max())
    room_pct = (high_52w - latest) / latest * 100
    good_room = 8 <= room_pct <= 40
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    lower_band = sma20 - 2 * std20
    touched_recent = bool((low.tail(7) <= lower_band.tail(7) * 1.01).any())
    bouncing = bool(touched_recent and latest > lower_band.iloc[-1])
    ret_3m = (latest / float(close.iloc[-63]) - 1) * 100 if len(close) > 63 else 0
    potential = ret_3m > 0
    glevels = gann_levels(latest)
    prev_close = float(close.iloc[-6]) if len(close) > 6 else latest
    gann_crossed = any(prev_close < lvl <= latest for lvl in glevels)
    gup = sorted([l for l in glevels if l > latest])
    next_gann = gup[0] if gup else None
    gann_approach = bool(next_gann and (next_gann - latest) / latest * 100 <= 5)
    gann_condition = bool(gann_crossed and gann_approach)
    below_r, above_r = resistance_levels(high, latest)
    resistance_crossed = len(below_r) > 0
    next_resistance = above_r[0] if above_r else round(high_52w, 2)
    conditions = {
        "Uptrend": bool(uptrend),
        "TrendReversed": reversed_recent,
        "AboveHMA_Buy": hma_condition,
        "RoomTo52wHigh": bool(good_room),
        "BBBounce": bouncing,
        "GrowthPotential": bool(potential),
        "GannCrossApproach": gann_condition,
        "ResistanceCrossed": bool(resistance_crossed),
    }
    score = sum(conditions.values())
    buy_price = round(latest, 2)
    target_candidates = [buy_price * (1 + MIN_PROFIT_PCT / 100)]
    if next_resistance:
        target_candidates.append(next_resistance)
    if next_gann:
        target_candidates.append(next_gann)
    target_price = round(max(target_candidates), 2)
    expected_profit_pct = round((target_price - buy_price) / buy_price * 100, 1)
    stop_loss = round(buy_price * 0.95, 2)
    circuit_info = check_circuit_pattern(df)
    return {
        "Symbol": symbol.replace(".NS", ""),
        "BuyPrice": buy_price,
        "Target": target_price,
        "Profit%": expected_profit_pct,
        "StopLoss": stop_loss,
        "Score": score,
        "NextResistance": round(next_resistance, 2) if next_resistance else None,
        "NextGann": round(next_gann, 2) if next_gann else None,
        "52wHigh": round(high_52w, 2),
        "RoomTo52wHigh%": round(room_pct, 1),
        **conditions,
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
    dfres = dfres.sort_values(["Score", "Profit%"], ascending=[False, False])
    shortlist = dfres[
        (dfres["Score"] >= MIN_SCORE)
        & (dfres["Profit%"] >= MIN_PROFIT_PCT)
        & (dfres["CircuitSignal"] != "AVOID")
    ]
    dfres.to_csv("data/swing_full.csv", index=False)
    shortlist.to_csv("data/swing_shortlist.csv", index=False)
    print(f"Shortlist: {len(shortlist)} stocks")
    return shortlist


def get_current_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1d", "interval": "1m"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        return round(float(data["chart"]["result"][0]["meta"]["regularMarketPrice"]), 2)
    except Exception:
        return None


def manage_positions(shortlist):
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
    if slots_needed > 0 and shortlist is not None and not shortlist.empty:
        candidates = (
            shortlist[~shortlist["Symbol"].isin(held_symbols)]
            .sort_values("Profit%", ascending=False)
            .head(slots_needed)
        )
        for _, r in candidates.iterrows():
            new_entries.append(
                {
                    "Symbol": r["Symbol"],
                    "EntryDate": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "BuyPrice": r["BuyPrice"],
                    "Target": r["Target"],
                    "StopLoss": r["StopLoss"],
                }
            )
            today_rows.append(
                {
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Symbol": r["Symbol"],
                    "BuyPrice": r["BuyPrice"],
                    "CurrentPrice": r["BuyPrice"],
                    "Target": r["Target"],
                    "StopLoss": r["StopLoss"],
                    "PnL%": 0.0,
                    "Status": "HOLDING",
                }
            )
            print(f"  NEW ENTRY: {r['Symbol']} @ {r['BuyPrice']} (replacing closed slot)")

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

    print("\n=== SWING PORTFOLIO SUMMARY ===")
    print(
        f"Total Entry Value: {total_invested:.2f} | Current Value: {total_current_value:.2f} | Overall P&L: {overall_pnl_pct}%"
    )
    print(
        f"Holdings: {len(open_rows)} | Target Hit Today: {len(closed_today) and len([r for r in closed_today if r['Status'] == 'TARGET HIT'])} | SL Hit Today: {len(closed_today) and len([r for r in closed_today if r['Status'] == 'SL HIT'])}"
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
    print("=== SWING SCANNER ===")
    shortlist = run_scan()
    manage_positions(shortlist)
