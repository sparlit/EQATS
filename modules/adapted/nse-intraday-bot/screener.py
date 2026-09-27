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
Parallel NSE screener — ORB + VWAP Pullback + Breakout+Retest strategy.
Stock list pulled LIVE from NSE API (no hardcoding).
Returns only signals that pass ALL hard rules (score 80+/150).
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from data_fetcher import get_intraday_data, get_prev_day_high_low
from nse_stocks import get_nse_stocks
from strategy import _get_kill_zone, score_stock

from config import CAPITAL, MAX_STOCKS, SCAN_WORKERS, STRONG_SCORE


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _scan_one(symbol: str, ist_time: datetime) -> dict | None:
    """Fetch + score one stock. Returns signal dict or None."""
    try:
        df5 = get_intraday_data(symbol, "5m")
        df15 = get_intraday_data(symbol, "15m")
        if df5.empty or df15.empty:
            return None
        pdh, pdl = get_prev_day_high_low(symbol)
        sig = score_stock(df5, df15, symbol, pdh, pdl, ist_time, capital=CAPITAL)
        if sig and sig.get("score", 0) >= STRONG_SCORE:
            return sig
    except Exception as e:
        print(f"[SCREENER] {symbol}: {e}")
    return None


def scan_market() -> list:
    """
    Parallel scan of all live NSE stocks.
    Returns strong setups sorted by score descending.
    """
    stocks = get_nse_stocks()[:MAX_STOCKS]
    ist_time = _now_ist()
    strong = []

    kz_name, _ = _get_kill_zone(ist_time.hour, ist_time.minute)
    print(f"\n[SCAN] {len(stocks)} stocks | {SCAN_WORKERS} workers | threshold={STRONG_SCORE}/150 | KZ={kz_name}")
    start = time.time()

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        futures = {pool.submit(_scan_one, s, ist_time): s for s in stocks}
        for fut in as_completed(futures):
            sig = fut.result()
            if sig:
                strong.append(sig)
                print(
                    f"  [STRONG] {sig['symbol']:14s} {sig['signal']:4s} "
                    f"setup={sig.get('setup', '?'):18s} "
                    f"score={sig['score']}/150 ({sig['score_pct']}%)  "
                    f"[{sig['signal_strength']}]  "
                    f"entry=₹{sig['entry']}  t1=₹{sig['t1']}  t2=₹{sig['t2']}"
                )

    elapsed = round(time.time() - start, 1)
    strong.sort(key=lambda x: x["score"], reverse=True)
    print(f"[SCAN] Done in {elapsed}s — {len(strong)} strong setup(s)")
    return strong


def quick_check_one(symbol: str) -> dict | None:
    """Single-stock check — used by /check Telegram command."""
    return _scan_one(symbol, _now_ist())
