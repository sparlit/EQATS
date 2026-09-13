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

from log_utils import get_logger

log = get_logger("daily_update")


def _safe(name, fn):
    log.info(f"START {name}")
    try:
        fn()
        log.info(f"OK    {name}")
        return True
    except Exception as e:
        log.exception(f"FAIL  {name}: {e}")
        return False


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
    log.info("=" * 50)
    log.info("DAILY UPDATE START")
    results = {}
    results["prices"] = _safe("prices", lambda: __import__("ingest_prices").run(show_every=0))
    results["technicals"] = _safe("technicals", lambda: __import__("technicals").compute_all())
    results["scan"] = _safe("scan", lambda: __import__("scan").run())
    results["ml"] = _safe("ml", lambda: __import__("ml_predict").predict_all())
    results["pwin"] = _safe("pwin", _pwin)
    results["toppicks"] = _safe("toppicks", _toppicks)
    results["events"] = _safe("events", lambda: __import__("events").detect())

    def _swing():
        import swing_live

        swing_live.update_outcomes()
        swing_live.scan()

    results["swing"] = _safe("swing", _swing)

    results["telegram"] = _safe("telegram", _telegram)
    results["sheets"] = _safe("sheets", _sheets)

    ok = sum(1 for v in results.values() if v)
    log.info(f"DAILY UPDATE COMPLETE — {ok}/{len(results)} steps ok")
    log.info("=" * 50)
    return results


if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
