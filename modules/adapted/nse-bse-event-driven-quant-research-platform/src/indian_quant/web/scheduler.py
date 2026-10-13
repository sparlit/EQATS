from __future__ import annotations

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


"""APScheduler background service for daily signal cache refresh.

Runs inside the FastAPI process:
    - 18:00 IST daily (Mon-Fri): full cache rebuild (PostgreSQL + Redis)
    - Every 15 min during market hours (08:30–15:30 IST, Mon-Fri): warm Redis
    - Every 30 min during evening (18:00–21:00 IST, Mon-Fri): warm Redis

Usage:
    - Automatically started when web app starts
    - Manual trigger: POST /admin/refresh-cache (protected)
"""


import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("quant.scheduler")

_scheduler: BackgroundScheduler | None = None
TZ_IST = timezone(timedelta(hours=5, minutes=30))


def _is_weekday() -> bool:
    return datetime.now(TZ_IST).weekday() < 5


def _is_market_hours() -> bool:
    now = datetime.now(TZ_IST)
    return _is_weekday() and 8 <= now.hour < 16


def _is_evening_hours() -> bool:
    now = datetime.now(TZ_IST)
    return _is_weekday() and 18 <= now.hour < 21


def _full_cache_rebuild() -> None:
    """Run cache_signals.py to rebuild PostgreSQL + Redis cache."""
    if not _is_weekday():
        return
    logger.info("Starting full cache rebuild...")
    try:
        result = subprocess.run(
            [sys.executable, "scripts/cache_signals.py"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            logger.info(f"Cache rebuild done: {result.stdout.strip()}")
        else:
            logger.error(f"Cache rebuild failed: {result.stderr[:500]}")
    except Exception as e:
        logger.error(f"Cache rebuild error: {e}")


def _warm_redis() -> None:
    """Quick Redis warm from PostgreSQL (no parquet scan)."""
    if not (_is_market_hours() or _is_evening_hours()):
        return  # skip outside active hours
    try:
        import json

        import pandas as pd
        from indian_quant.web.prod_config import get_pg_engine, get_redis_client

        engine = get_pg_engine()
        r = get_redis_client()

        df = pd.read_sql("SELECT * FROM cached_signals", engine)
        if df.empty:
            return

        signals = df.to_dict(orient="records")

        # Sanitize NaN/Inf before JSON serialization
        _sanitize_nan(signals)

        # Pre-compute composite scores
        _compute_scores(signals)

        def _j(obj):
            return json.dumps(obj, default=str)

        pipe = r.pipeline()
        pipe.delete("signals:all", "signals:buys", "signals:avoids")
        buys = [s for s in signals if s.get("signal_type") == "dz_hi_up"]
        avoids = [s for s in signals if s.get("signal_type") == "dz_hi_dn"]
        pipe.set("signals:all", _j(signals), ex=3600)
        pipe.set("signals:buys", _j(buys), ex=3600)
        pipe.set("signals:avoids", _j(avoids), ex=3600)
        pipe.set("signals:date", signals[0]["signal_date"] if signals else "", ex=3600)
        pipe.set("signals:count", str(len(signals)), ex=3600)
        for s in signals:
            pipe.hset("signals:by_symbol", s["symbol"], _j(s))
        pipe.expire("signals:by_symbol", 3600)
        pipe.execute()
        logger.info(f"Redis warmed: {len(signals)} signals")
    except Exception as e:
        logger.warning(f"Redis warm failed: {e}")


def _intra_day_signals() -> None:
    """Quick signal refresh during market hours (every 30 min)."""
    if not _is_market_hours():
        return
    logger.info("Intra-day signal refresh...")
    try:
        result = subprocess.run(
            [sys.executable, "scripts/daily_signals.py"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("Intra-day signals done")
        else:
            logger.warning(f"Intra-day signals failed: {result.stderr[:300]}")
    except Exception as e:
        logger.warning(f"Intra-day signals error: {e}")


def _sanitize_nan(signals: list[dict]) -> None:
    """Replace NaN/Inf floats with None in-place for JSON safety."""
    import math

    for s in signals:
        for k, v in s.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                s[k] = None


def _compute_scores(signals: list[dict]) -> None:
    """Compute composite score for each signal in-place. Sanitizes NaN."""
    import math

    def _safe(v):
        try:
            f = float(v)
            return None if math.isnan(f) or math.isinf(f) else f
        except (TypeError, ValueError):
            return None

    if not signals:
        return

    z_vals = []
    d_vals = []
    r_vals = []
    for s in signals:
        z = _safe(s.get("deliv_z"))
        d = _safe(s.get("deliv_pct"))
        r = _safe(s.get("ret_1d_pct"))
        z_vals.append(z if z is not None else 0)
        d_vals.append(d if d is not None else 0)
        r_vals.append(r if r is not None else 0)

    z_min, z_max = min(z_vals), max(z_vals)
    d_min, d_max = min(d_vals), max(d_vals)
    r_min, r_max = min(r_vals), max(r_vals)

    z_range = z_max - z_min or 1
    d_range = d_max - d_min or 1
    r_range = r_max - r_min or 1

    for i, s in enumerate(signals):
        zn = (z_vals[i] - z_min) / z_range
        dn = (d_vals[i] - d_min) / d_range
        rn = (r_vals[i] - r_min) / r_range
        s["_score"] = round(zn * 0.50 + dn * 0.30 + rn * 0.20, 4)


def start_scheduler() -> BackgroundScheduler:
    """Start the background scheduler. Call once at app startup."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Full rebuild daily at 18:00 IST Mon-Fri (after market close)
    _scheduler.add_job(
        _full_cache_rebuild,
        CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone="Asia/Kolkata"),
        id="daily_cache_rebuild",
        name="Daily cache rebuild (18:00 IST Mon-Fri)",
        replace_existing=True,
    )

    # Warm Redis every 15 min during market hours (Mon-Fri 08:00–16:00)
    _scheduler.add_job(
        _warm_redis,
        CronTrigger(minute="*/15", hour="8-15", day_of_week="mon-fri", timezone="Asia/Kolkata"),
        id="redis_warm_market",
        name="Redis warm (every 15m, market hours)",
        replace_existing=True,
    )

    # Warm Redis every 30 min during evening (Mon-Fri 18:00–21:00)
    _scheduler.add_job(
        _warm_redis,
        CronTrigger(minute="*/30", hour="18-20", day_of_week="mon-fri", timezone="Asia/Kolkata"),
        id="redis_warm_evening",
        name="Redis warm (every 30m, evening)",
        replace_existing=True,
    )

    # Intra-day signal refresh every 30 min during market hours (Mon-Fri 09:00–15:30)
    _scheduler.add_job(
        _intra_day_signals,
        CronTrigger(minute="*/30", hour="9-15", day_of_week="mon-fri", timezone="Asia/Kolkata"),
        id="intra_day_signals",
        name="Intra-day signal refresh (every 30m, market hours)",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started: daily rebuild @18:00, Redis warm 15m (market) / 30m (evening), "
        "signal refresh 30m (market) — all Mon-Fri only"
    )
    return _scheduler


def stop_scheduler() -> None:
    """Stop the scheduler. Call at app shutdown."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return scheduler status for admin endpoint."""
    if not _scheduler:
        return {"running": False}
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            }
        )
    return {"running": True, "jobs": jobs}
