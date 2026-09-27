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
Debug scanner — quick diagnostic for 10 key stocks.
Uses the live SMC/ICT strategy (score_stock) so output reflects
exactly what the production bot scores.

Run:  python debug_scan.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from datetime import datetime, timedelta, timezone

from data_fetcher import get_intraday_data, get_prev_day_high_low
from strategy import score_stock

STOCKS = [
    "RELIANCE",
    "SBIN",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "TCS",
    "BAJFINANCE",
    "AXISBANK",
    "WIPRO",
    "LT",
]


def _now_ist():
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def main():
    ist = _now_ist()
    print(f"\nDebug scan — {ist.strftime('%A %H:%M IST')}\n")
    print(f"{'SYMBOL':14s}  {'DIR':5s}  {'SCORE':10s}  {'STRENGTH':10s}  {'KILL ZONE':20s}  SIGNAL")
    print("-" * 90)

    for sym in STOCKS:
        try:
            df5 = get_intraday_data(sym, "5m")
            df15 = get_intraday_data(sym, "15m")
            if df5 is None or df5.empty or df15 is None or df15.empty:
                print(f"{sym:14s}  NO DATA")
                continue
            pdh, pdl = get_prev_day_high_low(sym)
            sig = score_stock(df5, df15, sym, pdh, pdl, ist)
            if sig:
                tp = sig.get("trade_params", {})
                print(
                    f"{sym:14s}  {sig['direction']:5s}  "
                    f"{sig['score']:3d}/150 ({sig['score_pct']:5.1f}%)  "
                    f"{sig['signal_strength']:10s}  "
                    f"{sig['kill_zone']:20s}  "
                    f"entry={tp.get('entry', '?')}  t1={tp.get('t1', '?')}  sl={tp.get('sl', '?')}"
                )
            else:
                print(f"{sym:14s}  no signal")
        except Exception as e:
            print(f"{sym:14s}  ERROR: {e}")

    print()


if __name__ == "__main__":
    main()
