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
intraday_scanner.py
Runs every 15 min during market hours via GitHub Actions.

Watches the full micro/small/mid-cap universe for:
 1. Volume surge starting right now (day-so-far pace or a sudden last-bar spike)
 2. Immediate bounce off a known daily support level -> Entry/SL/Targets calculated

Support levels, resistance levels, and 20-day avg volume are computed
once per trading day (cached to intraday_cache/levels_YYYYMMDD.csv)
then reused every cycle to avoid re-fetching 120 days of history
28 times a day.

Every new signal (deduped per stock+signal+day) is:
 - sent to Telegram immediately
 - appended to intraday_results_YYYYMMDD.csv (one file per day,
   growing across all cron cycles, same column style as the EOD scanner)
"""

import os
import time
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

# ---------------- CONFIG ----------------
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

CACHE_DIR = "intraday_cache"
NSE_INDEX_FILES = [
    "ind_niftymidcap150list.csv",
    "ind_niftysmallcap250list.csv",
]
STOCK_LIST_CSV = "microcap_universe.csv"

DEFAULT_STOCK_LIST = [
    "RVNL.NS",
    "IRFC.NS",
    "SUZLON.NS",
    "YESBANK.NS",
    "IDEA.NS",
    "SOUTHBANK.NS",
    "PNB.NS",
    "IOB.NS",
    "UCOBANK.NS",
    "CENTRALBK.NS",
]

PIVOT_WINDOW = 3
SUPPORT_TOUCH_TOLERANCE = 0.015
SUPPORT_MIN_TOUCHES = 2
BOUNCE_MARGIN = 0.003  # current price must be >= 0.3% above day's low

INTRADAY_INTERVAL = "5m"
BARS_PER_DAY = 75  # 375 trading minutes / 5-min bars
INTRADAY_VOL_SURGE_MULT = 1.8  # day-so-far cumulative volume vs expected pace
INTRADAY_SPIKE_MULT = 3.0  # last single 5-min bar vs expected per-bar volume

# Trade level calculation (same logic as EOD scanner)
SL_BUFFER_PCT = 0.015
ENTRY_ZONE_PCT = 0.008
RR_MULTIPLES = [1.5, 2.5, 4.0]

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0"}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ---------------- TIME / MARKET HOURS ----------------
def now_ist():
    return datetime.now(IST)


def market_open_now():
    n = now_ist()
    if n.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return MARKET_OPEN <= n.time() <= MARKET_CLOSE


# ---------------- STOCK LIST ----------------
def load_stock_list():
    symbols = []
    for fname in NSE_INDEX_FILES:
        if os.path.exists(fname):
            try:
                df = pd.read_csv(fname)
                col = "Symbol" if "Symbol" in df.columns else df.columns[2]
                syms = df[col].dropna().astype(str).str.strip().tolist()
                syms = [s + ".NS" for s in syms if not s.endswith(".NS")]
                symbols.extend(syms)
            except Exception as e:
                print(f"Found {fname} but couldn't parse it: {e}")

    if symbols:
        return sorted(set(symbols))

    if os.path.exists(STOCK_LIST_CSV):
        try:
            return pd.read_csv(STOCK_LIST_CSV)["symbol"].tolist()
        except Exception as e:
            print(f"Found {STOCK_LIST_CSV} but couldn't read it ({e}); using default list.")

    print("No stock list files found — using hardcoded DEFAULT_STOCK_LIST.")
    return DEFAULT_STOCK_LIST


# ---------------- DATA FETCH ----------------
def fetch_daily_data(symbol, days=120):
    params = {"range": f"{days}d", "interval": "1d", "includePrePost": "false"}
    try:
        r = requests.get(YAHOO_URL.format(symbol=symbol), params=params, headers=HEADERS, timeout=10)
        result = r.json()["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(ts, unit="s"),
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "close": q["close"],
                "volume": q["volume"],
            }
        ).dropna()
        return df.reset_index(drop=True)
    except Exception:
        return None


def fetch_intraday_data(symbol):
    params = {"range": "1d", "interval": INTRADAY_INTERVAL, "includePrePost": "false"}
    try:
        r = requests.get(YAHOO_URL.format(symbol=symbol), params=params, headers=HEADERS, timeout=10)
        result = r.json()["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {
                "time": pd.to_datetime(ts, unit="s"),
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "close": q["close"],
                "volume": q["volume"],
            }
        ).dropna()
        return df.reset_index(drop=True)
    except Exception:
        return None


# ---------------- SWING POINTS / SUPPORT / RESISTANCE ----------------
def find_swing_points(df, window=PIVOT_WINDOW):
    highs, lows = [], []
    for i in range(window, len(df) - window):
        seg_h = df["high"].iloc[i - window : i + window + 1]
        seg_l = df["low"].iloc[i - window : i + window + 1]
        if df["high"].iloc[i] == seg_h.max():
            highs.append((i, df["high"].iloc[i]))
        if df["low"].iloc[i] == seg_l.min():
            lows.append((i, df["low"].iloc[i]))
    return highs, lows


def find_support_levels(df, tolerance=SUPPORT_TOUCH_TOLERANCE, min_touches=SUPPORT_MIN_TOUCHES):
    _, lows = find_swing_points(df)
    if not lows:
        return []
    levels, used = [], set()
    low_vals = [l[1] for l in lows]
    for i, lv in enumerate(low_vals):
        if i in used:
            continue
        cluster, cluster_idx = [lv], {i}
        for j, lv2 in enumerate(low_vals):
            if j != i and j not in used and abs(lv2 - lv) / lv <= tolerance:
                cluster.append(lv2)
                cluster_idx.add(j)
        if len(cluster) >= min_touches:
            levels.append(float(np.mean(cluster)))
            used |= cluster_idx
    return levels


def find_resistance_levels(df):
    highs, _ = find_swing_points(df)
    return sorted({round(h[1], 2) for h in highs})


# ---------------- TRADE LEVELS (Entry / SL / Targets) ----------------
def calculate_trade_levels(base_level, current_price, resistances):
    entry_low = round(base_level, 2)
    entry_high = round(base_level * (1 + ENTRY_ZONE_PCT), 2)
    sl = round(base_level * (1 - SL_BUFFER_PCT), 2)
    risk = entry_low - sl

    targets = [r for r in resistances if r > current_price][:3]

    idx = len(targets)
    while len(targets) < 3:
        targets.append(round(entry_low + risk * RR_MULTIPLES[idx], 2))
        idx += 1

    return entry_low, entry_high, sl, targets[0], targets[1], targets[2]


# ---------------- LEVELS CACHE ----------------
def build_levels_cache(symbols, cache_path):
    print(f"Building today's support/resistance cache for {len(symbols)} symbols (first run of the day)...")
    rows = []
    for i, sym in enumerate(symbols):
        df = fetch_daily_data(sym, days=120)
        if df is None or len(df) < 30:
            time.sleep(0.2)
            continue
        levels = find_support_levels(df)
        resistances = find_resistance_levels(df)
        avg_vol_20d = float(df["volume"].iloc[-20:].mean())
        rows.append(
            {
                "symbol": sym,
                "levels": ";".join(f"{l:.2f}" for l in levels),
                "resistances": ";".join(f"{r:.2f}" for r in resistances),
                "avg_vol_20d": avg_vol_20d,
            }
        )
        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(symbols)} levels built")
        time.sleep(0.2)

    cache_df = pd.DataFrame(rows)
    cache_df.to_csv(cache_path, index=False)
    print(f"Saved levels cache: {cache_path} ({len(cache_df)} symbols)")
    return cache_df.set_index("symbol")


def load_levels_cache(cache_path):
    df = pd.read_csv(cache_path)
    df["levels"] = df["levels"].fillna("").apply(lambda s: [float(x) for x in str(s).split(";") if x])
    df["resistances"] = df["resistances"].fillna("").apply(lambda s: [float(x) for x in str(s).split(";") if x])
    return df.set_index("symbol")


# ---------------- SIGNAL CHECK ----------------
def check_intraday_signals(df, levels, avg_vol_20d):
    if df is None or df.empty:
        return None

    day_low = df["low"].min()
    current_price = df["close"].iloc[-1]
    cumulative_volume = df["volume"].sum()
    elapsed_bars = len(df)
    last_candle_vol = df["volume"].iloc[-1]

    expected_per_bar = (avg_vol_20d / BARS_PER_DAY) if avg_vol_20d and avg_vol_20d > 0 else 0
    expected_cumulative = expected_per_bar * elapsed_bars

    vol_ratio_day = cumulative_volume / expected_cumulative if expected_cumulative > 0 else 0
    vol_ratio_spike = last_candle_vol / expected_per_bar if expected_per_bar > 0 else 0
    volume_surge = vol_ratio_day >= INTRADAY_VOL_SURGE_MULT or vol_ratio_spike >= INTRADAY_SPIKE_MULT

    support_bounce, bounce_level = False, None
    for lvl in levels:
        touched = abs(day_low - lvl) / lvl <= SUPPORT_TOUCH_TOLERANCE
        bounced = (current_price - day_low) / day_low >= BOUNCE_MARGIN
        above_level = current_price >= lvl * (1 - SUPPORT_TOUCH_TOLERANCE)
        if touched and bounced and above_level:
            support_bounce, bounce_level = True, lvl
            break

    return {
        "current_price": current_price,
        "day_low": day_low,
        "volume_surge": volume_surge,
        "vol_ratio_day": vol_ratio_day,
        "vol_ratio_spike": vol_ratio_spike,
        "support_bounce": support_bounce,
        "bounce_level": bounce_level,
    }


# ---------------- RESULTS CSV (grows across the day) ----------------
def append_result_row(results_path, row_dict):
    file_exists = os.path.exists(results_path)
    pd.DataFrame([row_dict]).to_csv(results_path, mode="a", header=not file_exists, index=False)


# ---------------- TELEGRAM ----------------
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping send.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            print(f"[!] Telegram send failed: {r.text}")
    except Exception as e:
        print(f"[!] Telegram send error: {e}")


# ---------------- MAIN ----------------
def run_intraday_scan():
    if not market_open_now():
        print(f"Outside market hours ({now_ist().strftime('%H:%M IST')}) — skipping.")
        return

    os.makedirs(CACHE_DIR, exist_ok=True)
    date_str = now_ist().strftime("%Y%m%d")
    levels_cache_path = f"{CACHE_DIR}/levels_{date_str}.csv"
    alerted_cache_path = f"{CACHE_DIR}/alerted_{date_str}.csv"
    results_path = f"intraday_results_{date_str}.csv"

    symbols = load_stock_list()
    print(f"Universe size: {len(symbols)} symbols")

    if os.path.exists(levels_cache_path):
        levels_df = load_levels_cache(levels_cache_path)
        print(f"Loaded cached support/resistance levels for {len(levels_df)} symbols.")
    else:
        levels_df = build_levels_cache(symbols, levels_cache_path)

    alerted_keys = set(pd.read_csv(alerted_cache_path)["key"].tolist()) if os.path.exists(alerted_cache_path) else set()

    new_alerts = 0
    cycle_time = now_ist().strftime("%H:%M:%S")

    for _i, sym in enumerate(symbols):
        if sym not in levels_df.index:
            continue

        row = levels_df.loc[sym]
        levels = row["levels"] if isinstance(row["levels"], list) else []
        resistances = row["resistances"] if isinstance(row["resistances"], list) else []
        avg_vol_20d = row["avg_vol_20d"]

        intraday_df = fetch_intraday_data(sym)
        sig = check_intraday_signals(intraday_df, levels, avg_vol_20d)
        if sig is None:
            time.sleep(0.15)
            continue

        clean_sym = sym.replace(".NS", "")

        if sig["volume_surge"]:
            key = f"{sym}_VOLSURGE"
            if key not in alerted_keys:
                msg = (
                    f"VOLUME SURGE — {clean_sym}\n"
                    f"Price: {sig['current_price']:.2f}\n"
                    f"Day-vol pace: {sig['vol_ratio_day']:.1f}x | Last-bar spike: {sig['vol_ratio_spike']:.1f}x\n"
                    f"{now_ist().strftime('%H:%M IST')}"
                )
                send_telegram_message(msg)
                alerted_keys.add(key)
                new_alerts += 1

                append_result_row(
                    results_path,
                    {
                        "timestamp": cycle_time,
                        "symbol": clean_sym,
                        "signal_type": "VOLUME_SURGE",
                        "price": round(sig["current_price"], 2),
                        "day_low": round(sig["day_low"], 2),
                        "vol_ratio_day": round(sig["vol_ratio_day"], 2),
                        "vol_ratio_spike": round(sig["vol_ratio_spike"], 2),
                        "bounce_level": "",
                        "entry_low": "",
                        "entry_high": "",
                        "stop_loss": "",
                        "target1": "",
                        "target2": "",
                        "target3": "",
                    },
                )
                time.sleep(1)

        if sig["support_bounce"]:
            key = f"{sym}_SUPPORTBOUNCE"
            if key not in alerted_keys:
                entry_low, entry_high, sl, t1, t2, t3 = calculate_trade_levels(
                    sig["bounce_level"], sig["current_price"], resistances
                )

                msg = (
                    f"SUPPORT BOUNCE — {clean_sym}\n"
                    f"Price: {sig['current_price']:.2f} | Day low: {sig['day_low']:.2f}\n"
                    f"Support level: {sig['bounce_level']:.2f}\n"
                    f"Entry: {entry_low}-{entry_high} | SL: {sl}\n"
                    f"T1: {t1} | T2: {t2} | T3: {t3}\n"
                    f"{now_ist().strftime('%H:%M IST')}"
                )
                send_telegram_message(msg)
                alerted_keys.add(key)
                new_alerts += 1

                append_result_row(
                    results_path,
                    {
                        "timestamp": cycle_time,
                        "symbol": clean_sym,
                        "signal_type": "SUPPORT_BOUNCE",
                        "price": round(sig["current_price"], 2),
                        "day_low": round(sig["day_low"], 2),
                        "vol_ratio_day": round(sig["vol_ratio_day"], 2),
                        "vol_ratio_spike": round(sig["vol_ratio_spike"], 2),
                        "bounce_level": sig["bounce_level"],
                        "entry_low": entry_low,
                        "entry_high": entry_high,
                        "stop_loss": sl,
                        "target1": t1,
                        "target2": t2,
                        "target3": t3,
                    },
                )
                time.sleep(1)

        time.sleep(0.15)

    pd.DataFrame({"key": sorted(alerted_keys)}).to_csv(alerted_cache_path, index=False)
    print(f"\nCycle complete. New alerts this cycle: {new_alerts}. Total alerted today: {len(alerted_keys)}.")
    if os.path.exists(results_path):
        print(f"Results file: {results_path} (grows with each new signal across the day)")


if __name__ == "__main__":
    run_intraday_scan()
