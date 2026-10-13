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
NSE Intraday Bot — Main process  (SMC + ICT strategy)
======================================================
* Scans all live NSE stocks every 5 min during Kill Zones
* Fires Telegram alert the moment a stock qualifies (score 65+/150)
* Session limits: max 3 trades/day, block after 2 consecutive losses
* Chatbot runs in a background thread
"""
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from notifier import fire_alert, telegram_send
from screener import scan_market

from config import MAX_CONSECUTIVE_LOSSES, MAX_TRADES_PER_SESSION, SCAN_INTERVAL, STRONG_SCORE

# telegram_bot (interactive chatbot) is optional — NSE alerts work without it
try:
    from telegram_bot import run_chatbot
except Exception:
    run_chatbot = None

# ── LOGGING ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── IST HELPERS ────────────────────────────────────────────────


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def is_market_open() -> bool:
    n = _now_ist()
    if n.weekday() >= 5:
        return False
    t = n.hour * 100 + n.minute
    return 915 <= t <= 1530


def is_pre_market() -> bool:
    n = _now_ist()
    if n.weekday() >= 5:
        return False
    t = n.hour * 100 + n.minute
    return 900 <= t < 915


# ── SESSION RISK CONTROLS ──────────────────────────────────────

_session_fires: dict = {}  # {date: count}
_alerted: set = set()
_alert_date: date = None


def _reset_if_new_day():
    global _alerted, _alert_date
    today = date.today()
    if _alert_date != today:
        _alerted = set()
        _alert_date = today
        log.info("New trading day — dedup tracker reset")


def _fires_today() -> int:
    return _session_fires.get(date.today(), 0)


def _record_fire(symbol: str):
    today = date.today()
    _session_fires[today] = _session_fires.get(today, 0) + 1
    _alerted.add(symbol)


def _consecutive_losses_today() -> int:
    """Count SL HITs in a row (from the end) for today's closed trades."""
    try:
        from signal_logger import _load

        today_str = str(date.today())
        data = _load()
        closed = [
            r
            for r in data
            if r.get("date") == today_str and r.get("status") in ("TARGET HIT", "SL HIT")
        ]
        count = 0
        for r in reversed(closed):
            if r["status"] == "SL HIT":
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


def _session_ok() -> tuple:
    """Returns (allowed: bool, reason: str | None)."""
    fires = _fires_today()
    if fires >= MAX_TRADES_PER_SESSION:
        return False, f"Session limit reached ({fires}/{MAX_TRADES_PER_SESSION} trades today)"

    losses = _consecutive_losses_today()
    if losses >= MAX_CONSECUTIVE_LOSSES:
        return False, f"{losses} consecutive losses — session blocked for today"

    return True, None


# ── DEDUP: don't re-alert same stock same day ──────────────────


def _new_signals(signals: list) -> list:
    _reset_if_new_day()
    return [s for s in signals if s["symbol"] not in _alerted]


# ── MAIN SCAN LOOP ─────────────────────────────────────────────


def market_watcher():
    greeted_today = None
    closed_today = None

    while True:
        now = _now_ist()
        today = now.date()
        is_thu = today.weekday() == 3

        # ── Pre-market greeting ────────────────────────────────
        if is_pre_market() and greeted_today != today:
            kz_note = (
                "Only KZ3 entries today (Thursday expiry)."
                if is_thu
                else "Active kill zones: KZ1 (9:15-10:00), KZ2 (11:15-11:45), KZ3 (13:30-14:15)."
            )
            telegram_send(
                f"Good morning! NSE Intraday Bot starting.\n\n"
                f"Strategy : ORB + VWAP Pullback + Breakout+Retest\n"
                f"Scoring  : 150-pt scale — min {STRONG_SCORE}/150 to alert\n"
                f"Risk     : 1% capital per trade  |  T1=1.5R  T2=PDH/PDL\n"
                f"Session  : max {MAX_TRADES_PER_SESSION} trades, "
                f"block after {MAX_CONSECUTIVE_LOSSES} consecutive losses\n\n"
                f"{kz_note}"
            )
            greeted_today = today
            log.info("Pre-market greeting sent")

        # ── Market hours: scan ─────────────────────────────────
        if is_market_open():
            log.info("Scanning market (kill zones active)...")
            try:
                signals = scan_market()
                fresh = _new_signals(signals)

                for sig in fresh:
                    allowed, reason = _session_ok()
                    if not allowed:
                        log.info("Fire blocked: %s", reason)
                        telegram_send(f"Signal ready but blocked:\n{reason}")
                        break

                    fire_alert(sig)
                    _record_fire(sig["symbol"])

                if not fresh:
                    log.info("No new strong setups this cycle")

            except Exception as e:
                log.error("Scan error: %s", e)

            # ── End-of-day wrap-up ─────────────────────────────
            t_int = now.hour * 100 + now.minute
            if t_int >= 1525 and closed_today != today:
                fires = _fires_today()
                losses = _consecutive_losses_today()
                telegram_send(
                    f"Market closed.\n\n"
                    f"Trades fired today : {fires}\n"
                    f"Consecutive losses : {losses}\n"
                    f"Dashboard          : http://localhost:5000\n\n"
                    f"See you tomorrow at 9:15 AM IST."
                )
                closed_today = today
                log.info("End-of-day message sent")
                time.sleep(60 * 60 * 14)
                continue

            time.sleep(SCAN_INTERVAL * 60)

        else:
            time.sleep(60)


# ── ENTRY POINT ────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  NSE INTRADAY BOT  —  ORB + VWAP + Breakout+Retest")
    print(f"  Score threshold  : {STRONG_SCORE}/150")
    print(f"  Scan interval    : every {SCAN_INTERVAL} min")
    print(f"  Max trades/day   : {MAX_TRADES_PER_SESSION}")
    print(f"  Max consec losses: {MAX_CONSECUTIVE_LOSSES}")
    print("  Data source      : Live NSE (no hardcoding)")
    print("=" * 60)

    telegram_send(
        f"NSE Intraday Bot started.\n\n"
        f"Strategy : ORB + VWAP Pullback + Breakout+Retest\n"
        f"Score    : 150-pt scale (min {STRONG_SCORE} to alert)\n"
        f"Risk     : 1% capital per trade\n\n"
        f"Kill Zones:\n"
        f"  KZ1 : 09:31 - 10:30\n"
        f"  KZ2 : 11:15 - 11:45\n"
        f"  KZ3 : 13:30 - 14:30\n\n"
        f"Max {MAX_TRADES_PER_SESSION} trades/day. "
        f"Session blocked after {MAX_CONSECUTIVE_LOSSES} consecutive losses."
    )

    if run_chatbot is not None:
        threading.Thread(target=run_chatbot, daemon=True).start()
    else:
        log.warning(
            "telegram_bot module missing — interactive chatbot disabled "
            "(NSE scanning + alerts still active)"
        )
    market_watcher()
