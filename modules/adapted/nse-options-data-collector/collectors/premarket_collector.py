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
Pre-Market Global Cues Collector — fetches global market data before 9:15 AM.

Collects: US indices, US VIX, US futures, commodities, currencies, Asian markets.
Saves to data/global_cues/ as daily parquet files.

Usage:
    python -m collectors.premarket_collector              # single fetch now
    python -m collectors.premarket_collector --schedule   # run at 8:45 AM + 10:00 AM (Asian)
    python -m collectors.premarket_collector --info       # show collected data
"""

import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.logger import get_logger

log = get_logger("premarket")

IST = timezone(timedelta(hours=5, minutes=30))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "global_cues")

US_TICKERS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "us_vix": "^VIX",
    "sp_futures": "ES=F",
}

COMMODITY_TICKERS = {
    "gold": "GC=F",
    "crude": "CL=F",
    "brent": "BZ=F",
    "copper": "HG=F",
}

CURRENCY_TICKERS = {
    "usdinr": "USDINR=X",
    "dxy": "DX-Y.NYB",
}

ASIAN_TICKERS = {
    "hangseng": "^HSI",
    "nikkei": "^N225",
    "sgx_nifty": "^NSEI",
}


def _fetch_tickers(ticker_map: dict, period: str = "5d") -> dict:
    results = {}
    all_symbols = list(ticker_map.values())

    try:
        data = yf.download(all_symbols, period=period, progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        log.warning("yfinance bulk download failed: %s — falling back to individual", e)
        data = None

    for name, ticker in ticker_map.items():
        try:
            if data is not None and not data.empty:
                if len(ticker_map) == 1:
                    closes = data["Close"].dropna()
                elif ticker in data["Close"].columns:
                    closes = data["Close"][ticker].dropna()
                else:
                    closes = pd.Series(dtype=float)
            else:
                closes = pd.Series(dtype=float)

            if closes.empty:
                t = yf.Ticker(ticker)
                hist = t.history(period=period)
                if hist.empty:
                    log.warning("No data for %s (%s)", name, ticker)
                    results[name] = {"close": 0, "prev_close": 0, "chg_pct": 0}
                    continue
                closes = hist["Close"].dropna()

            if len(closes) >= 2:
                current = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                chg_pct = round((current - prev) / prev * 100, 3) if prev != 0 else 0
            elif len(closes) == 1:
                current = float(closes.iloc[-1])
                prev = current
                chg_pct = 0
            else:
                current = prev = chg_pct = 0

            results[name] = {
                "close": round(current, 2),
                "prev_close": round(prev, 2),
                "chg_pct": chg_pct,
            }
        except Exception as e:
            log.warning("Failed to fetch %s (%s): %s", name, ticker, e)
            results[name] = {"close": 0, "prev_close": 0, "chg_pct": 0}

    return results


def collect_premarket() -> pd.DataFrame:
    """Collect US + commodity + currency data (run at 8:45 AM)."""
    now = datetime.now(IST)
    timestamp = now.isoformat()

    log.info("Fetching US markets, commodities, currencies...")
    us = _fetch_tickers(US_TICKERS)
    commodities = _fetch_tickers(COMMODITY_TICKERS)
    currencies = _fetch_tickers(CURRENCY_TICKERS)

    row = {"timestamp": timestamp, "date": date.today().isoformat(), "session": "premarket"}
    for group in [us, commodities, currencies]:
        for name, vals in group.items():
            row[f"{name}_close"] = vals["close"]
            row[f"{name}_prev_close"] = vals["prev_close"]
            row[f"{name}_chg_pct"] = vals["chg_pct"]

    log.info(
        "Pre-market: SP500=%.1f (%.2f%%), Crude=%.1f (%.2f%%), USDINR=%.2f (%.2f%%)",
        us.get("sp500", {}).get("close", 0),
        us.get("sp500", {}).get("chg_pct", 0),
        commodities.get("crude", {}).get("close", 0),
        commodities.get("crude", {}).get("chg_pct", 0),
        currencies.get("usdinr", {}).get("close", 0),
        currencies.get("usdinr", {}).get("chg_pct", 0),
    )
    return pd.DataFrame([row])


def collect_asian() -> pd.DataFrame:
    """Collect Asian market data (run at 10:00 AM after HK/JP open)."""
    now = datetime.now(IST)
    timestamp = now.isoformat()
    log.info("Fetching Asian markets...")
    asian = _fetch_tickers(ASIAN_TICKERS)
    row = {"timestamp": timestamp, "date": date.today().isoformat(), "session": "asian"}
    for name, vals in asian.items():
        row[f"{name}_close"] = vals["close"]
        row[f"{name}_prev_close"] = vals["prev_close"]
        row[f"{name}_chg_pct"] = vals["chg_pct"]
    log.info(
        "Asian: HangSeng=%.1f (%.2f%%), Nikkei=%.1f (%.2f%%)",
        asian.get("hangseng", {}).get("close", 0),
        asian.get("hangseng", {}).get("chg_pct", 0),
        asian.get("nikkei", {}).get("close", 0),
        asian.get("nikkei", {}).get("chg_pct", 0),
    )
    return pd.DataFrame([row])


def save_data(df: pd.DataFrame):
    if df.empty:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    today_str = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"global_{today_str}.parquet")
    if os.path.isfile(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    log.info("Saved to %s", path)


def run_schedule():
    """Run at 8:45 AM (US+commodities+currencies) and 10:00 AM (Asian)."""
    from utils.market_hours import is_market_day

    if not is_market_day():
        log.info("Market holiday — skipping pre-market collection")
        return

    schedule = {"08:45": "premarket", "10:00": "asian"}
    done = set()
    log.info("Pre-market collector scheduled for: %s", list(schedule.keys()))

    while True:
        now = datetime.now(IST)
        now_str = now.strftime("%H:%M")

        if len(done) >= len(schedule) or now.hour >= 11:
            log.info("All pre-market data collected, stopping")
            break

        for t, session in schedule.items():
            if now_str == t and session not in done:
                log.info("Running %s collection at %s", session, t)
                df = collect_premarket() if session == "premarket" else collect_asian()
                save_data(df)
                done.add(session)
                time.sleep(61)
                break
        else:
            time.sleep(30)


def show_info():
    if not os.path.isdir(DATA_DIR):
        print("No global cues data collected yet")
        return
    files = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("global_") and f.endswith(".parquet"))
    if not files:
        print("No global cues files found")
        return
    for f in files:
        path = os.path.join(DATA_DIR, f)
        df = pd.read_parquet(path)
        sessions = df["session"].unique() if "session" in df.columns else ["unknown"]
        print(f"  {f}: {len(df)} rows, sessions: {list(sessions)}")
    print(f"\nTotal: {len(files)} days")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pre-Market Global Cues Collector")
    parser.add_argument("--schedule", action="store_true", help="Run at 8:45 AM + 10:00 AM")
    parser.add_argument("--asian", action="store_true", help="Fetch Asian markets only")
    parser.add_argument("--info", action="store_true", help="Show collected data summary")
    args = parser.parse_args()

    if args.info:
        show_info()
    elif args.asian:
        df = collect_asian()
        save_data(df)
        if not df.empty:
            print(df.to_string(index=False))
    elif args.schedule:
        run_schedule()
    else:
        log.info("Collecting pre-market global cues...")
        df = collect_premarket()
        if not df.empty:
            save_data(df)
            print("\nGlobal cues collected:")
            for col in df.columns:
                if col not in ("timestamp", "date", "session"):
                    print(f"  {col}: {df[col].iloc[0]}")
        else:
            print("No data collected")
