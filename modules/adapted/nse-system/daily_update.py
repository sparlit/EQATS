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


import sys

import events
import ingest_prices
import ml_predict
import scan
import swing_live
import technicals


def _safe(name, fn):
    print(f"... {name}")
    try:
        fn()
        print(f"ok {name}")
    except Exception as e:
        print(f"skip {name}: {e}")


def _telegram():
    import telegram_alerts

    telegram_alerts.report()


def _sheets():
    import sheets_sync

    sheets_sync.sync()


def _pwin():
    import pwin_cache

    pwin_cache.refresh_all()


def _toppicks():
    import top_picks

    top_picks.compute(force=True)


def run():
    _safe("prices", lambda: ingest_prices.run(show_every=0))
    _safe("technicals", technicals.compute_all)
    _safe("scan", scan.run)
    _safe("ml", ml_predict.predict_all)
    _safe("pwin", _pwin)
    _safe("toppicks", _toppicks)
    _safe("events", events.detect)
    _safe("swing", lambda: (swing_live.update_outcomes(), swing_live.scan()))
    _safe("telegram", _telegram)
    _safe("sheets", _sheets)
    print("DAILY UPDATE COMPLETE")


if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
