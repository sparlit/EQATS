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
EOD Data Collector — runs after market close to save daily data.

Collects:
  1. Today's 5-min candles for all 37 symbols
  2. Sector index daily candles (IT, Pharma, Auto, Metal, FMCG, Midcap)
  3. FII/DII activity across all segments (cash + 4 F&O segments)
  4. VIX intraday 5-min candles
  5. NIFTY/BNF futures basis (futures - spot)
  6. Market breadth (advance/decline, % above EMA20)

Saves to data/eod/ as daily parquet files.
Scheduled at 16:00 IST after CAS completes.

Usage:
    python -m collectors.eod_collector              # run all collections now
    python -m collectors.eod_collector --schedule   # wait and run at 16:00
    python -m collectors.eod_collector --candles    # 5-min candles only
    python -m collectors.eod_collector --fii        # FII/DII only
    python -m collectors.eod_collector --sectors    # sector indices only
    python -m collectors.eod_collector --info       # show collected data
"""

import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import utils.upstox_data as ud
from utils.logger import get_logger

log = get_logger("eod_collector")

IST = timezone(timedelta(hours=5, minutes=30))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "eod")

SYMBOLS = [
    "NIFTY",
    "BANKNIFTY",
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "BHARTIARTL",
    "SBIN",
    "ITC",
    "LT",
    "HINDUNILVR",
    "KOTAKBANK",
    "AXISBANK",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "BAJFINANCE",
    "WIPRO",
    "HCLTECH",
    "ADANIENT",
    "TATAMOTORS",
    "TATASTEEL",
    "POWERGRID",
    "NTPC",
    "ONGC",
    "COALINDIA",
    "JSWSTEEL",
    "DRREDDY",
    "BAJAJFINSV",
    "ASIANPAINT",
    "TECHM",
    "INDUSINDBK",
    "M&M",
    "CIPLA",
    "EICHERMOT",
    "SBILIFE",
]

SECTOR_KEYS = {
    "NIFTY_IT": "NSE_INDEX|Nifty IT",
    "NIFTY_PHARMA": "NSE_INDEX|Nifty Pharma",
    "NIFTY_AUTO": "NSE_INDEX|Nifty Auto",
    "NIFTY_METAL": "NSE_INDEX|Nifty Metal",
    "NIFTY_FMCG": "NSE_INDEX|Nifty FMCG",
    "NIFTY_ENERGY": "NSE_INDEX|Nifty Energy",
    "NIFTY_MIDCAP": "NSE_INDEX|NIFTY MID SELECT",
}

FII_SEGMENTS = [
    "NSE_EQ|CASH",
    "NSE_FO|INDEX_FUTURES",
    "NSE_FO|INDEX_OPTIONS",
    "NSE_FO|STOCK_FUTURES",
    "NSE_FO|STOCK_OPTIONS",
]


def collect_candles() -> int:
    candle_dir = os.path.join(DATA_DIR, "candles_5min")
    os.makedirs(candle_dir, exist_ok=True)
    today_str = date.today().isoformat()
    saved = 0
    for sym in SYMBOLS:
        try:
            df = ud.fetch_intraday_candles(sym, days=1, interval_min=5)
            if df is None or df.empty:
                log.warning("No candles for %s", sym)
                continue
            today_bars = df[df.index.date == date.today()]
            if today_bars.empty:
                log.warning("No today bars for %s", sym)
                continue
            path = os.path.join(candle_dir, f"{sym}_{today_str}.parquet")
            today_bars.to_parquet(path, engine="pyarrow")
            saved += 1
            time.sleep(0.3)
        except Exception as e:
            log.warning("Candle fetch failed for %s: %s", sym, e)
    log.info("5-min candles saved: %d/%d symbols", saved, len(SYMBOLS))
    return saved


def collect_sectors() -> pd.DataFrame:
    rows = []
    today_str = date.today().isoformat()
    for name, key in SECTOR_KEYS.items():
        try:
            old_keys = ud.INSTRUMENT_KEYS.copy()
            ud.INSTRUMENT_KEYS[name] = key
            df = ud.fetch_daily_candles(name, days=5)
            ud.INSTRUMENT_KEYS.update(old_keys)
            if name not in old_keys:
                del ud.INSTRUMENT_KEYS[name]
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else latest
            rows.append(
                {
                    "date": today_str,
                    "sector": name,
                    "instrument_key": key,
                    "open": float(latest["open"]),
                    "high": float(latest["high"]),
                    "low": float(latest["low"]),
                    "close": float(latest["close"]),
                    "prev_close": float(prev["close"]),
                    "chg_pct": round((float(latest["close"]) - float(prev["close"])) / float(prev["close"]) * 100, 3),
                }
            )
            time.sleep(0.3)
        except Exception as e:
            log.warning("Sector fetch failed for %s: %s", name, e)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    log.info("Sector data: %d/%d indices collected", len(df), len(SECTOR_KEYS))
    return df


def collect_fii_dii() -> pd.DataFrame:
    rows = []
    today_str = date.today().isoformat()
    for segment in FII_SEGMENTS:
        try:
            data = ud.get_fii_activity(segment)
            if data:
                rows.append(
                    {
                        "date": today_str,
                        "type": "FII",
                        "segment": segment,
                        "buy_amount": data["buy_amount"],
                        "sell_amount": data["sell_amount"],
                        "net_amount": data["net_amount"],
                    }
                )
            time.sleep(0.3)
        except Exception as e:
            log.warning("FII fetch failed for %s: %s", segment, e)
    try:
        dii = ud.get_dii_activity()
        if dii:
            rows.append(
                {
                    "date": today_str,
                    "type": "DII",
                    "segment": "NSE_EQ|CASH",
                    "buy_amount": dii["buy_amount"],
                    "sell_amount": dii["sell_amount"],
                    "net_amount": dii["net_amount"],
                }
            )
    except Exception as e:
        log.warning("DII fetch failed: %s", e)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    log.info("FII/DII: %d segment records collected", len(df))
    return df


def collect_vix_intraday() -> pd.DataFrame:
    try:
        df = ud.fetch_intraday_candles("VIX", days=1, interval_min=5)
        if df is None or df.empty:
            return pd.DataFrame()
        today_bars = df[df.index.date == date.today()]
        if today_bars.empty:
            return pd.DataFrame()
        log.info("VIX intraday: %d bars", len(today_bars))
        return today_bars
    except Exception as e:
        log.warning("VIX intraday fetch failed: %s", e)
        return pd.DataFrame()


def collect_futures_basis() -> pd.DataFrame:
    rows = []
    today_str = date.today().isoformat()
    for sym in ["NIFTY", "BANKNIFTY"]:
        try:
            spot_data = ud.get_spot(sym)
            if not spot_data:
                continue
            spot = spot_data.get("ltp", 0)
            if spot == 0:
                continue
            fut_keys = ud.resolve_futures_keys([sym])
            fut_key = fut_keys.get(sym)
            if not fut_key:
                continue
            fut_data = ud.get_ltp_detail(fut_key)
            if not fut_data:
                continue
            fut_price = fut_data.get("last_price", 0)
            if fut_price == 0:
                continue
            basis = fut_price - spot
            basis_pct = round(basis / spot * 100, 4)
            rows.append(
                {
                    "date": today_str,
                    "symbol": sym,
                    "spot": round(spot, 2),
                    "futures": round(fut_price, 2),
                    "basis": round(basis, 2),
                    "basis_pct": basis_pct,
                }
            )
        except Exception as e:
            log.warning("Futures basis failed for %s: %s", sym, e)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    log.info("Futures basis: %s", {r["symbol"]: f"{r['basis_pct']}%%" for r in rows})
    return df


def collect_breadth() -> pd.DataFrame:
    today_str = date.today().isoformat()
    stocks = [s for s in SYMBOLS if s not in ("NIFTY", "BANKNIFTY")]
    advances = declines = above_ema20 = total = 0
    for sym in stocks:
        try:
            df = ud.fetch_daily_candles(sym, days=30)
            if df is None or len(df) < 20:
                continue
            total += 1
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            if float(latest["close"]) > float(prev["close"]):
                advances += 1
            else:
                declines += 1
            ema20 = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
            if float(latest["close"]) > float(ema20):
                above_ema20 += 1
            time.sleep(0.2)
        except Exception as e:
            log.warning("Breadth calc failed for %s: %s", sym, e)
    if total == 0:
        return pd.DataFrame()
    row = {
        "date": today_str,
        "advances": advances,
        "declines": declines,
        "unchanged": total - advances - declines,
        "total": total,
        "adv_decline_ratio": round(advances / declines, 3) if declines > 0 else 99.0,
        "pct_above_ema20": round(above_ema20 / total * 100, 1),
    }
    log.info(
        "Breadth: %d adv / %d dec (ratio %.2f), %.1f%% above EMA20",
        advances,
        declines,
        row["adv_decline_ratio"],
        row["pct_above_ema20"],
    )
    return pd.DataFrame([row])


def save_eod(name: str, df: pd.DataFrame):
    if df.empty:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    today_str = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"{name}_{today_str}.parquet")
    if os.path.isfile(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    log.info("Saved %s to %s (%d rows)", name, path, len(df))


def run_all():
    log.info("=== EOD Collection Starting ===")
    start = time.time()
    log.info("--- 1/6: 5-min candles (37 symbols) ---")
    collect_candles()
    log.info("--- 2/6: Sector indices ---")
    sectors_df = collect_sectors()
    save_eod("sectors", sectors_df)
    log.info("--- 3/6: FII/DII flows ---")
    fii_df = collect_fii_dii()
    save_eod("fii_dii", fii_df)
    log.info("--- 4/6: VIX intraday ---")
    vix_df = collect_vix_intraday()
    if not vix_df.empty:
        vix_dir = os.path.join(DATA_DIR, "candles_5min")
        os.makedirs(vix_dir, exist_ok=True)
        vix_path = os.path.join(vix_dir, f"VIX_{date.today().isoformat()}.parquet")
        vix_df.to_parquet(vix_path, engine="pyarrow")
    log.info("--- 5/6: Futures basis ---")
    basis_df = collect_futures_basis()
    save_eod("futures_basis", basis_df)
    log.info("--- 6/6: Market breadth ---")
    breadth_df = collect_breadth()
    save_eod("breadth", breadth_df)
    elapsed = time.time() - start
    log.info("=== EOD Collection Complete (%.0fs) ===", elapsed)


def run_schedule():
    from utils.market_hours import is_market_day

    if not is_market_day():
        log.info("Market holiday — skipping EOD collection")
        return

    log.info("EOD Collector scheduled for 16:00 IST")
    while True:
        now = datetime.now(IST)
        now_str = now.strftime("%H:%M")
        if now_str == "16:00":
            run_all()
            break
        if now.hour >= 17:
            log.info("Past 17:00, running EOD now")
            run_all()
            break
        time.sleep(30)
    log.info("EOD Collector done")


def show_info():
    if not os.path.isdir(DATA_DIR):
        print("No EOD data collected yet")
        return
    candle_dir = os.path.join(DATA_DIR, "candles_5min")
    if os.path.isdir(candle_dir):
        candle_files = [f for f in os.listdir(candle_dir) if f.endswith(".parquet")]
        dates = {f.split("_")[-1].replace(".parquet", "") for f in candle_files}
        print(f"  Candles: {len(candle_files)} files across {len(dates)} days")
    other_files = sorted(
        f for f in os.listdir(DATA_DIR) if f.endswith(".parquet") and not os.path.isdir(os.path.join(DATA_DIR, f))
    )
    for f in other_files:
        path = os.path.join(DATA_DIR, f)
        df = pd.read_parquet(path)
        print(f"  {f}: {len(df)} rows")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EOD Data Collector")
    parser.add_argument("--schedule", action="store_true", help="Wait and run at 16:00 IST")
    parser.add_argument("--candles", action="store_true", help="5-min candles only")
    parser.add_argument("--sectors", action="store_true", help="Sector indices only")
    parser.add_argument("--fii", action="store_true", help="FII/DII only")
    parser.add_argument("--vix", action="store_true", help="VIX intraday only")
    parser.add_argument("--basis", action="store_true", help="Futures basis only")
    parser.add_argument("--breadth", action="store_true", help="Market breadth only")
    parser.add_argument("--info", action="store_true", help="Show collected data summary")
    args = parser.parse_args()

    if args.info:
        show_info()
    elif args.schedule:
        run_schedule()
    elif args.candles:
        collect_candles()
    elif args.sectors:
        df = collect_sectors()
        save_eod("sectors", df)
        if not df.empty:
            print(df.to_string(index=False))
    elif args.fii:
        df = collect_fii_dii()
        save_eod("fii_dii", df)
        if not df.empty:
            print(df.to_string(index=False))
    elif args.vix:
        df = collect_vix_intraday()
        if not df.empty:
            print(f"VIX: {len(df)} bars")
    elif args.basis:
        df = collect_futures_basis()
        save_eod("futures_basis", df)
        if not df.empty:
            print(df.to_string(index=False))
    elif args.breadth:
        df = collect_breadth()
        save_eod("breadth", df)
        if not df.empty:
            print(df.to_string(index=False))
    else:
        run_all()
