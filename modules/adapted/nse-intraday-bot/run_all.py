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
Unified entry point — runs NSE, Gold, BTC, and Swing bots concurrently
plus the Flask dashboard, all in a single process.

Usage:
  python run_all.py
  (or double-click run_bot.bat on Windows)

Dashboard: http://localhost:5000
"""
import os
import sys
import threading
import time

# ── IST time helper ───────────────────────────────────────────
from datetime import datetime, timedelta, timezone


def _now_ist():
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


# ── Thread targets ────────────────────────────────────────────


def _start_nse():
    """NSE intraday bot — ORB + VWAP + Breakout+Retest strategy."""
    try:
        from main import market_watcher, run_chatbot

        threading.Thread(target=run_chatbot, daemon=True, name="NSE-chat").start()
        market_watcher()
    except Exception as e:
        print(f"[NSE] Fatal error: {e}")


def _start_gold():
    """Gold (XAUUSD) bot — ICT+SMC 5-point confluence, threshold 120/150."""
    try:
        from run_gold import run_gold_watcher

        run_gold_watcher()
    except Exception as e:
        print(f"[GOLD] Fatal error: {e}")


def _start_btc():
    """Bitcoin (BTCUSDT) bot — SMC structure, threshold 65/150."""
    try:
        from run_btc import run_btc_watcher

        run_btc_watcher()
    except Exception as e:
        print(f"[BTC] Fatal error: {e}")


def _start_swing():
    """
    Swing bot — 5-layer SMC daily scanner.
    Runs once at 15:35 IST every market day, then repeats the next day.
    Also does a live-price status update for all open positions every hour.
    """
    try:
        import schedule
        from run_swing import main as swing_main
        from run_swing import update_swing_statuses

        # ── Schedule daily scan at 15:35 IST ─────────────────
        schedule.every().day.at("15:35").do(swing_main)

        # ── Update open position prices every 30 min ─────────
        schedule.every(30).minutes.do(lambda: update_swing_statuses(silent=True))

        print("[SWING] Scheduler started — daily scan at 15:35 IST, status update every 30 min")

        # Run immediately on startup if not yet scanned today
        from run_swing import _load_trades, _today_str

        df = _load_trades()
        today = _today_str()
        scanned_today = (not df.empty) and (df["date"] == today).any()
        if not scanned_today:
            print("[SWING] No scan today yet — running now...")
            threading.Thread(target=swing_main, daemon=True, name="SWING-scan-now").start()

        while True:
            schedule.run_pending()
            time.sleep(30)

    except ImportError:
        # 'schedule' package not installed — fall back to simple loop
        print("[SWING] 'schedule' not installed — using simple daily loop")
        _swing_simple_loop()
    except Exception as e:
        print(f"[SWING] Fatal error: {e}")
        import traceback

        traceback.print_exc()


def _swing_simple_loop():
    """Fallback: check every 5 min, run scan once at/after 15:35 IST."""
    from run_swing import _load_trades, _today_str, update_swing_statuses
    from run_swing import main as swing_main

    last_scan_date = None

    while True:
        try:
            now = _now_ist()
            today = _today_str()
            t_int = now.hour * 100 + now.minute

            # ── Update open positions every 30 min ───────────
            if now.minute % 30 == 0:
                update_swing_statuses(silent=True)

            # ── Daily scan at 15:35 IST (or on startup if missed) ─
            df = _load_trades()
            scanned_today = (not df.empty) and (df["date"] == today).any()

            if not scanned_today and last_scan_date != today:
                if t_int >= 1535 or t_int < 930:  # after close or startup catch-up
                    print(f"[SWING] Triggering daily scan for {today}...")
                    swing_main()
                    last_scan_date = today

        except Exception as e:
            print(f"[SWING-LOOP] Error: {e}")

        time.sleep(5 * 60)  # check every 5 minutes


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    ist = _now_ist()
    print("=" * 62)
    print("  UNIFIED TRADING BOT  |  NSE + GOLD + BTC + SWING")
    print(f"  Started : {ist.strftime('%d %b %Y  %H:%M IST')}")
    print("  Dashboard: http://localhost:5000")
    print("=" * 62)
    print()
    print("  NSE   : ORB + VWAP Pullback + Breakout+Retest  (score 95+/150)")
    print("  GOLD  : ICT + SMC 5-point confluence            (score 120+/150)")
    print("  BTC   : SMC structure + ICT filters             (score 65+/150)")
    print("  SWING : 5-Layer SMC daily F&O scan              (score 7.0+/10)")
    print()

    # ── Startup Telegram message ──────────────────────────────
    try:
        from notifier import telegram_send

        telegram_send(
            "✅ Unified Trading Bot started.\n\n"
            "Running: NSE Intraday | Gold | Bitcoin | Swing Scanner\n\n"
            "NSE Strategy : ORB + VWAP + Breakout+Retest\n"
            "  KZ1 09:31-10:30 | KZ2 11:15-11:45 | KZ3 13:30-14:30\n"
            "  Min score : 95/150  |  No daily cap\n\n"
            "Gold Strategy : ICT + SMC (5-point confluence)\n"
            "  London KZ 13:30-16:30 | NY KZ 18:30-21:30 IST\n"
            "  Min score : 120/150\n\n"
            "BTC Strategy  : SMC + ICT filters\n"
            "  Min score : 65/150\n\n"
            "Swing Scanner : 5-Layer SMC  |  Daily at 15:35 IST\n"
            "  Scans all NSE F&O stocks  |  Min score : 7.0/10\n\n"
            "Dashboard: http://localhost:5000"
        )
        print("  [OK] Startup Telegram message sent")
    except Exception as e:
        print(f"  [WARN] Startup Telegram failed: {e}")

    # ── Launch all watchers as daemon threads ─────────────────
    threads = [
        threading.Thread(target=_start_nse, daemon=True, name="NSE"),
        threading.Thread(target=_start_gold, daemon=True, name="GOLD"),
        threading.Thread(target=_start_btc, daemon=True, name="BTC"),
        threading.Thread(target=_start_swing, daemon=True, name="SWING"),
    ]
    for t in threads:
        t.start()
        print(f"  [STARTED] {t.name} watcher thread")
        time.sleep(1)  # stagger startup

    print()
    print("  All 4 bots running. Starting dashboard...")
    print("  Open http://localhost:5000 in your browser.")
    print()

    # ── Flask dashboard runs in main thread ───────────────────
    try:
        import dashboard

        port = int(os.environ.get("PORT", 5000))
        dashboard.app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
        )
    except Exception as e:
        print(f"[DASHBOARD] Error: {e}")
        print("Dashboard failed — bots still running in background threads.")
        while True:
            time.sleep(60)
