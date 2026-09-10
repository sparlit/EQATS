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
Intraday OI + Option Chain Collector — collects OI + full chain for 37 symbols.

Runs every 15 min (9:20 to 15:29) + CAS closing price at 15:42.
Each snapshot collects:
  1. OI summary (ATM data, PCR, max OI strikes) -> data/oi_snapshots/
  2. Full option chain (all strikes x CE/PE: OI, IV, Greeks, bid/ask) -> data/option_chain/
15:29 snapshot captures last continuous price before CAS auction (15:30-15:40).

Usage:
    python -m collectors.oi_collector              # single OI snapshot now
    python -m collectors.oi_collector --chain      # single chain snapshot now
    python -m collectors.oi_collector --schedule   # every 15 min 9:20-15:29 + CAS at 15:42
    python -m collectors.oi_collector --info       # show collected data summary
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from utils.logger import get_logger
from utils.upstox_data import _BASE, _get

log = get_logger("oi_collector")

IST = timezone(timedelta(hours=5, minutes=30))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "oi_snapshots")
CHAIN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "option_chain")

STOCKS = [
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

INDICES = ["NIFTY", "BANKNIFTY"]

INDEX_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}

_key_cache: dict[str, str] = {}
_KEY_CACHE_FILE = os.path.join(DATA_DIR, "_instrument_keys.json")


def _load_key_cache():
    global _key_cache
    if os.path.isfile(_KEY_CACHE_FILE):
        with open(_KEY_CACHE_FILE) as f:
            _key_cache = json.load(f)


def _save_key_cache():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_KEY_CACHE_FILE, "w") as f:
        json.dump(_key_cache, f, indent=2)


def _has_fo_contracts(instrument_key: str) -> bool:
    data = _get(f"{_BASE}/option/contract", {"instrument_key": instrument_key}, timeout=10)
    if not data:
        return False
    today = date.today()
    return any(date.fromisoformat(c.get("expiry", "")[:10]) >= today for c in data if c.get("expiry", ""))


def _resolve_key(symbol: str, force_refresh: bool = False) -> str | None:
    if symbol in INDEX_KEYS:
        return INDEX_KEYS[symbol]
    if symbol in _key_cache and not force_refresh:
        return _key_cache[symbol]

    data = _get(
        f"{_BASE}/instruments/search",
        {
            "query": symbol,
            "exchanges": "NSE",
            "segments": "EQ",
        },
        timeout=10,
    )
    candidates = []
    if data:
        results = data if isinstance(data, list) else []
        for r in results:
            key = r.get("instrument_key", "")
            if key and key not in candidates:
                candidates.append(key)

    for key in candidates:
        if _has_fo_contracts(key):
            _key_cache[symbol] = key
            _save_key_cache()
            return key

    if candidates:
        key = candidates[0]
        _key_cache[symbol] = key
        _save_key_cache()
        return key
    return None


def _get_nearest_expiry(instrument_key: str) -> str | None:
    data = _get(f"{_BASE}/option/contract", {"instrument_key": instrument_key}, timeout=10)
    if not data:
        return None
    today = date.today()
    expiries = set()
    for contract in data:
        exp_str = contract.get("expiry", "")
        if not exp_str:
            continue
        try:
            exp_date = date.fromisoformat(exp_str[:10])
            if exp_date >= today:
                expiries.add(exp_str[:10])
        except ValueError:
            continue
    return min(expiries) if expiries else None


def _load_baseline() -> dict[str, dict]:
    today_str = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"oi_{today_str}.parquet")
    if not os.path.isfile(path):
        return {}
    df = pd.read_parquet(path)
    if df.empty:
        return {}
    first_ts = df["timestamp"].min()
    first = df[df["timestamp"] == first_ts]
    baseline = {}
    for _, row in first.iterrows():
        baseline[row["symbol"]] = {
            "spot": row["spot"],
            "total_ce_oi": row["total_ce_oi"],
            "total_pe_oi": row["total_pe_oi"],
            "atm_ce_ltp": row.get("atm_ce_ltp", 0),
            "atm_pe_ltp": row.get("atm_pe_ltp", 0),
        }
    return baseline


def _compute_oi_signal(premium_now: float, premium_open: float, oi_now: int, oi_open: int) -> str:
    if oi_open == 0 or premium_open == 0:
        return "NEUTRAL"
    price_up = premium_now > premium_open
    oi_up = oi_now > oi_open
    if oi_up and price_up:
        return "LONG_BUILD"
    if oi_up and not price_up:
        return "SHORT_BUILD"
    if not oi_up and price_up:
        return "SHORT_COVER"
    if not oi_up and not price_up:
        return "LONG_UNWIND"
    return "NEUTRAL"


def collect_snapshot() -> pd.DataFrame:
    """Collect OI snapshot for all stocks + indices."""
    now = datetime.now(IST)
    timestamp = now.isoformat()
    rows = []

    all_symbols = INDICES + STOCKS
    success = 0
    failed = []

    _load_key_cache()
    baseline = _load_baseline()

    for sym in all_symbols:
        key = _resolve_key(sym)
        if not key:
            log.warning("Could not resolve key for %s", sym)
            failed.append(sym)
            continue

        expiry = _get_nearest_expiry(key)
        if not expiry and sym in _key_cache:
            log.info("Retrying %s with fresh key lookup", sym)
            del _key_cache[sym]
            _save_key_cache()
            key = _resolve_key(sym, force_refresh=True)
            if key:
                expiry = _get_nearest_expiry(key)
        if not expiry:
            log.warning("No expiry found for %s", sym)
            failed.append(sym)
            continue

        oi_data = _get(
            f"{_BASE}/market/oi",
            {
                "instrument_key": key,
                "expiry": expiry,
                "date": date.today().isoformat(),
            },
            timeout=10,
        )

        if not oi_data:
            log.warning("OI API returned nothing for %s", sym)
            failed.append(sym)
            continue

        total_puts = int(oi_data.get("total_puts", 0) or 0)
        total_calls = int(oi_data.get("total_calls", 0) or 0)
        pcr = round(total_puts / total_calls, 4) if total_calls > 0 else 0.0
        spot = float(oi_data.get("spot_closing_price", 0) or 0)

        strike_data = oi_data.get("call_put_oi_data_list", [])
        max_ce_oi_strike = max_pe_oi_strike = 0
        max_ce_oi = max_pe_oi = 0

        for s in strike_data:
            ce_oi = int(s.get("call_oi", 0) or 0)
            pe_oi = int(s.get("put_oi", 0) or 0)
            strike = int(s.get("strike_price", 0) or 0)
            if ce_oi > max_ce_oi:
                max_ce_oi = ce_oi
                max_ce_oi_strike = strike
            if pe_oi > max_pe_oi:
                max_pe_oi = pe_oi
                max_pe_oi_strike = strike

        atm_ce_bid = atm_ce_ask = atm_ce_ltp = 0.0
        atm_pe_bid = atm_pe_ask = atm_pe_ltp = 0.0
        atm_strike = 0
        if spot > 0:
            chain_data = _get(
                f"{_BASE}/option/chain",
                {
                    "instrument_key": key,
                    "expiry_date": expiry,
                },
                timeout=10,
            )
            if chain_data:
                chain_rows = chain_data if isinstance(chain_data, list) else []
                closest = min(chain_rows, key=lambda r: abs(int(r.get("strike_price", 0)) - spot), default=None)
                if closest:
                    atm_strike = int(closest.get("strike_price", 0))
                    ce_md = closest.get("call_options", {}).get("market_data", {})
                    pe_md = closest.get("put_options", {}).get("market_data", {})
                    atm_ce_bid = float(ce_md.get("bid_price", 0) or 0)
                    atm_ce_ask = float(ce_md.get("ask_price", 0) or 0)
                    atm_ce_ltp = float(ce_md.get("ltp", 0) or 0)
                    atm_pe_bid = float(pe_md.get("bid_price", 0) or 0)
                    atm_pe_ask = float(pe_md.get("ask_price", 0) or 0)
                    atm_pe_ltp = float(pe_md.get("ltp", 0) or 0)

        base = baseline.get(sym, {})
        base_ce_oi = base.get("total_ce_oi", 0)
        base_pe_oi = base.get("total_pe_oi", 0)
        base_ce_ltp = base.get("atm_ce_ltp", 0)
        base_pe_ltp = base.get("atm_pe_ltp", 0)

        ce_oi_signal = _compute_oi_signal(atm_ce_ltp, base_ce_ltp, total_calls, base_ce_oi)
        pe_oi_signal = _compute_oi_signal(atm_pe_ltp, base_pe_ltp, total_puts, base_pe_oi)
        ce_oi_change_pct = round((total_calls - base_ce_oi) / base_ce_oi * 100, 2) if base_ce_oi > 0 else 0.0
        pe_oi_change_pct = round((total_puts - base_pe_oi) / base_pe_oi * 100, 2) if base_pe_oi > 0 else 0.0
        total_oi = total_calls + total_puts
        base_total_oi = base_ce_oi + base_pe_oi
        oi_change_pct = round((total_oi - base_total_oi) / base_total_oi * 100, 2) if base_total_oi > 0 else 0.0
        pcr_change = round(pcr - (base_pe_oi / base_ce_oi if base_ce_oi > 0 else 0), 4)

        rows.append(
            {
                "timestamp": timestamp,
                "symbol": sym,
                "expiry": expiry,
                "spot": spot,
                "total_ce_oi": total_calls,
                "total_pe_oi": total_puts,
                "pcr": pcr,
                "max_ce_oi": max_ce_oi,
                "max_ce_oi_strike": max_ce_oi_strike,
                "max_pe_oi": max_pe_oi,
                "max_pe_oi_strike": max_pe_oi_strike,
                "num_strikes": len(strike_data),
                "atm_strike": atm_strike,
                "atm_ce_ltp": atm_ce_ltp,
                "atm_ce_bid": atm_ce_bid,
                "atm_ce_ask": atm_ce_ask,
                "atm_ce_spread": round(atm_ce_ask - atm_ce_bid, 2),
                "atm_pe_ltp": atm_pe_ltp,
                "atm_pe_bid": atm_pe_bid,
                "atm_pe_ask": atm_pe_ask,
                "atm_pe_spread": round(atm_pe_ask - atm_pe_bid, 2),
                "ce_oi_signal": ce_oi_signal,
                "pe_oi_signal": pe_oi_signal,
                "oi_change_pct": oi_change_pct,
                "ce_oi_change_pct": ce_oi_change_pct,
                "pe_oi_change_pct": pe_oi_change_pct,
                "pcr_change": pcr_change,
            }
        )
        success += 1

        if success % 10 == 0:
            log.info("Progress: %d/%d collected", success, len(all_symbols))
        time.sleep(0.3)

    log.info("Snapshot complete: %d success, %d failed", success, len(failed))
    if failed:
        log.warning("Failed symbols: %s", failed)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def save_snapshot(df: pd.DataFrame):
    if df.empty:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    today_str = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"oi_{today_str}.parquet")
    if os.path.isfile(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    log.info("Saved %d rows to %s", len(df), path)


def _load_continuous_close() -> dict:
    today_str = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"oi_{today_str}.parquet")
    if not os.path.isfile(path):
        return {}
    df = pd.read_parquet(path)
    last_snap = df.sort_values("timestamp").groupby("symbol").last()
    return {sym: float(row["spot"]) for sym, row in last_snap.iterrows() if row["spot"] > 0}


def collect_cas_closing() -> pd.DataFrame:
    """Fetch CAS-determined closing prices at ~15:42 for all symbols."""
    now = datetime.now(IST)
    timestamp = now.isoformat()
    rows = []
    continuous = _load_continuous_close()

    _load_key_cache()
    all_symbols = INDICES + STOCKS
    success = 0

    for sym in all_symbols:
        if sym in INDEX_KEYS:
            key = INDEX_KEYS[sym]
        elif sym in _key_cache:
            key = _key_cache[sym]
        else:
            continue

        quote = _get(f"{_BASE}/market-quote/quotes", {"instrument_key": key}, timeout=10)
        if not quote:
            continue

        quote_data = quote if isinstance(quote, dict) else {}
        if not quote_data:
            if isinstance(quote, list) and quote:
                quote_data = quote[0]
            else:
                continue

        for _inst_key, q in quote_data.items() if isinstance(quote_data, dict) else [(sym, quote_data)]:
            if isinstance(q, dict):
                cas_price = float(q.get("last_price", 0) or q.get("ltp", 0) or 0)
                cont_price = continuous.get(sym, 0.0)
                divergence = round((cas_price - cont_price) / cont_price * 100, 4) if cont_price > 0 else 0.0
                rows.append(
                    {
                        "timestamp": timestamp,
                        "symbol": sym,
                        "snapshot_type": "CAS_CLOSE",
                        "cas_close": cas_price,
                        "continuous_close": cont_price,
                        "cas_divergence_pct": divergence,
                    }
                )
                success += 1
                break
        time.sleep(0.2)

    log.info("CAS closing prices collected: %d/%d symbols", success, len(all_symbols))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def save_cas_closing(df: pd.DataFrame):
    if df.empty:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    today_str = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"cas_{today_str}.parquet")
    df.to_parquet(path, engine="pyarrow", index=False)
    log.info("Saved CAS closing data to %s", path)


def collect_chain_snapshot() -> pd.DataFrame:
    """Collect full option chain (all strikes) for all symbols.

    Saves per-strike: OI, IV, delta, theta, gamma, vega, LTP, bid, ask, volume
    for both CE and PE sides.
    """
    now = datetime.now(IST)
    timestamp = now.isoformat()
    rows = []

    all_symbols = INDICES + STOCKS
    success = 0
    failed = []

    _load_key_cache()

    for sym in all_symbols:
        key = _resolve_key(sym)
        if not key:
            failed.append(sym)
            continue

        expiry = _get_nearest_expiry(key)
        if not expiry:
            failed.append(sym)
            continue

        spot_data = _get(
            f"{_BASE}/market/oi",
            {
                "instrument_key": key,
                "expiry": expiry,
                "date": date.today().isoformat(),
            },
            timeout=10,
        )
        spot = float(spot_data.get("spot_closing_price", 0) or 0) if spot_data else 0.0

        chain_data = _get(
            f"{_BASE}/option/chain",
            {
                "instrument_key": key,
                "expiry_date": expiry,
            },
            timeout=15,
        )

        if not chain_data:
            failed.append(sym)
            time.sleep(0.3)
            continue

        chain_rows = chain_data if isinstance(chain_data, list) else []
        for strike_row in chain_rows:
            strike = int(strike_row.get("strike_price", 0) or 0)
            if strike == 0:
                continue

            ce = strike_row.get("call_options", {})
            pe = strike_row.get("put_options", {})
            ce_md = ce.get("market_data", {})
            pe_md = pe.get("market_data", {})
            ce_greeks = ce.get("option_greeks", {})
            pe_greeks = pe.get("option_greeks", {})

            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": sym,
                    "expiry": expiry,
                    "spot": spot,
                    "strike": strike,
                    "ce_oi": int(ce_md.get("oi", 0) or 0),
                    "ce_volume": int(ce_md.get("volume", 0) or 0),
                    "ce_ltp": float(ce_md.get("ltp", 0) or 0),
                    "ce_bid": float(ce_md.get("bid_price", 0) or 0),
                    "ce_ask": float(ce_md.get("ask_price", 0) or 0),
                    "ce_iv": float(ce_greeks.get("iv", 0) or 0),
                    "ce_delta": float(ce_greeks.get("delta", 0) or 0),
                    "ce_theta": float(ce_greeks.get("theta", 0) or 0),
                    "ce_gamma": float(ce_greeks.get("gamma", 0) or 0),
                    "ce_vega": float(ce_greeks.get("vega", 0) or 0),
                    "pe_oi": int(pe_md.get("oi", 0) or 0),
                    "pe_volume": int(pe_md.get("volume", 0) or 0),
                    "pe_ltp": float(pe_md.get("ltp", 0) or 0),
                    "pe_bid": float(pe_md.get("bid_price", 0) or 0),
                    "pe_ask": float(pe_md.get("ask_price", 0) or 0),
                    "pe_iv": float(pe_greeks.get("iv", 0) or 0),
                    "pe_delta": float(pe_greeks.get("delta", 0) or 0),
                    "pe_theta": float(pe_greeks.get("theta", 0) or 0),
                    "pe_gamma": float(pe_greeks.get("gamma", 0) or 0),
                    "pe_vega": float(pe_greeks.get("vega", 0) or 0),
                }
            )

        success += 1
        if success % 10 == 0:
            log.info("Chain progress: %d/%d collected", success, len(all_symbols))
        time.sleep(0.3)

    log.info("Chain snapshot: %d success (%d strikes), %d failed", success, len(rows), len(failed))
    if failed:
        log.warning("Chain failed symbols: %s", failed)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def save_chain_snapshot(df: pd.DataFrame):
    if df.empty:
        return
    os.makedirs(CHAIN_DIR, exist_ok=True)
    today_str = date.today().isoformat()
    path = os.path.join(CHAIN_DIR, f"chain_{today_str}.parquet")
    if os.path.isfile(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    log.info("Saved %d chain rows to %s", len(df), path)


def run_schedule():
    """Run every 15 min from 9:20-15:29 IST + CAS closing at 15:42."""
    from utils.market_hours import is_market_day

    if not is_market_day():
        log.info("Market holiday — skipping OI collection")
        return

    schedule_times = []
    h, m = 9, 20
    while h < 15 or (h == 15 and m <= 20):
        schedule_times.append(f"{h:02d}:{m:02d}")
        m += 15
        if m >= 60:
            h += 1
            m -= 60
    schedule_times.append("15:29")
    cas_time = "15:42"
    cas_done = False

    log.info(
        "OI+Chain Collector: %d snapshots every 15 min (%s to %s) + CAS at %s",
        len(schedule_times),
        schedule_times[0],
        schedule_times[-1],
        cas_time,
    )

    while True:
        now = datetime.now(IST)
        now_str = now.strftime("%H:%M")

        if now.hour >= 16 and cas_done:
            log.info("Market closed, stopping scheduler")
            break

        if now_str == cas_time and not cas_done:
            log.info("Collecting CAS closing prices at %s", cas_time)
            cas_df = collect_cas_closing()
            save_cas_closing(cas_df)
            cas_done = True
            time.sleep(61)
            continue

        for t in schedule_times:
            if now_str == t:
                log.info("Running scheduled snapshot at %s", t)
                df = collect_snapshot()
                save_snapshot(df)
                log.info("Running chain snapshot at %s", t)
                chain_df = collect_chain_snapshot()
                save_chain_snapshot(chain_df)
                time.sleep(61)
                break
        else:
            time.sleep(30)


def show_info():
    if os.path.isdir(DATA_DIR):
        files = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("oi_") and f.endswith(".parquet"))
        if files:
            print("=== OI Snapshots ===")
            total_rows = 0
            for f in files:
                path = os.path.join(DATA_DIR, f)
                df = pd.read_parquet(path)
                total_rows += len(df)
                timestamps = df["timestamp"].nunique()
                symbols = df["symbol"].nunique()
                print(f"  {f}: {len(df)} rows, {timestamps} snapshots, {symbols} symbols")
            print(f"Total: {len(files)} days, {total_rows} rows\n")

    if os.path.isdir(CHAIN_DIR):
        files = sorted(f for f in os.listdir(CHAIN_DIR) if f.startswith("chain_") and f.endswith(".parquet"))
        if files:
            print("=== Option Chain ===")
            total_rows = 0
            for f in files:
                path = os.path.join(CHAIN_DIR, f)
                df = pd.read_parquet(path)
                total_rows += len(df)
                timestamps = df["timestamp"].nunique()
                symbols = df["symbol"].nunique()
                strikes = df["strike"].nunique()
                print(f"  {f}: {len(df)} rows, {timestamps} snapshots, {symbols} symbols, {strikes} strikes")
            print(f"Total: {len(files)} days, {total_rows} rows\n")

    if not os.path.isdir(DATA_DIR) and not os.path.isdir(CHAIN_DIR):
        print("No data collected yet")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Intraday OI + Option Chain Collector")
    parser.add_argument("--schedule", action="store_true", help="Every 15 min 9:20-15:29 + CAS at 15:42")
    parser.add_argument("--cas", action="store_true", help="Collect CAS closing prices now")
    parser.add_argument("--chain", action="store_true", help="Collect full option chain snapshot now")
    parser.add_argument("--info", action="store_true", help="Show collected data summary")
    args = parser.parse_args()

    if args.info:
        show_info()
    elif args.cas:
        log.info("Collecting CAS closing prices...")
        cas_df = collect_cas_closing()
        if not cas_df.empty:
            save_cas_closing(cas_df)
            print(f"\nCAS closing prices for {len(cas_df)} symbols:")
            print(cas_df.to_string(index=False))
        else:
            print("No CAS data collected")
    elif args.chain:
        log.info("Collecting full option chain...")
        chain_df = collect_chain_snapshot()
        if not chain_df.empty:
            save_chain_snapshot(chain_df)
            symbols = chain_df["symbol"].nunique()
            print(f"\nCollected chain: {symbols} symbols, {len(chain_df)} strike rows")
        else:
            print("No chain data collected")
    elif args.schedule:
        run_schedule()
    else:
        log.info("Collecting single OI snapshot...")
        df = collect_snapshot()
        if not df.empty:
            save_snapshot(df)
            print(f"\nCollected {len(df)} symbols:")
            print(df[["symbol", "spot", "total_ce_oi", "total_pe_oi", "pcr"]].to_string(index=False))
        else:
            print("No data collected")
