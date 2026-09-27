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
Live check — scans 10 key stocks and sends results to Telegram.
Uses current screener (quick_check_one) and notifier (telegram_send).

Run:  python send_live_check.py
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from notifier import telegram_send
from screener import quick_check_one

CHECK_STOCKS = [
    "WIPRO",
    "TCS",
    "ITC",
    "SBIN",
    "RELIANCE",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "LT",
    "AXISBANK",
]

STRONG_THRESHOLD = 65  # /150


def _bar(score: int, total: int = 150) -> str:
    filled = int(score / total * 10)
    return "#" * filled + "." * (10 - filled)


def main():
    telegram_send("Live Analysis — checking 10 stocks now...")

    for sym in CHECK_STOCKS:
        print(f"Checking {sym}...")
        sig = quick_check_one(sym)

        if not sig:
            telegram_send(f"{sym} — No signal / no data")
            continue

        score = sig.get("score", 0)
        dir_ = sig.get("direction", "?")
        tp = sig.get("trade_params", {})
        entry = tp.get("entry", sig.get("entry", "?"))
        t1 = tp.get("t1", sig.get("t1", "?"))
        t2 = tp.get("t2", sig.get("t2", sig.get("target", "?")))
        sl = tp.get("sl", sig.get("sl", "?"))
        sl_pct = tp.get("sl_pct", "?")
        rr = tp.get("rr_ratio", sig.get("rr", "?"))
        print(f"  {sym}: {dir_} score={score}/150")

        if score >= STRONG_THRESHOLD:
            label = "*** STRONG ALERT ***"
        elif score >= 50:
            label = "WATCH — Forming"
        else:
            label = "WEAK — Not Ready"

        reasons = "\n".join(f"  + {r}" for r in sig.get("reasons", [])) or "  — No signals"

        msg = (
            f"{'BUY' if dir_ == 'LONG' else 'SELL'}  {sym}  —  {label}\n"
            f"Score : {score}/150  [{_bar(score)}]  ({sig.get('score_pct', '?')}%)\n"
            f"Entry : Rs {entry}   T1 : Rs {t1}   T2 : Rs {t2}\n"
            f"SL    : Rs {sl}  ({sl_pct}%)   R:R 1:{rr}\n"
            f"Kill Zone : {sig.get('kill_zone', '?')}\n"
            f"Signals:\n{reasons}"
        )
        telegram_send(msg)
        time.sleep(0.5)

    telegram_send("Check complete!")
    print("All results sent to Telegram!")


if __name__ == "__main__":
    main()
