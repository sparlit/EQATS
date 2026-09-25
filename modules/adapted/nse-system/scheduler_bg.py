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


"""Background scheduler — dq + daily + swing + macro + institutional + weekly jobs."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

IST = pytz.timezone("Asia/Kolkata")

_scheduler = None


def _data_quality_job():
    print("[SCHEDULER] data quality started")
    try:
        import data_quality

        data_quality.run(send_alert=True)
        print("[SCHEDULER] data quality complete")
    except Exception as e:
        print(f"[SCHEDULER] data quality failed: {e}")


def _daily_job():
    print("[SCHEDULER] daily update started")
    try:
        import daily_update

        daily_update.run()
        print("[SCHEDULER] daily update complete")
    except Exception as e:
        print(f"[SCHEDULER] daily update failed: {e}")


def _swing_job():
    print("[SCHEDULER] swing scan started")
    try:
        import swing_live

        swing_live.update_outcomes()
        swing_live.scan()
        _drift_check()
        print("[SCHEDULER] swing scan complete")
    except Exception as e:
        print(f"[SCHEDULER] swing scan failed: {e}")


def _institutional_job():
    print("[SCHEDULER] institutional refresh started")
    try:
        import institutional

        institutional.refresh()
        print("[SCHEDULER] institutional refresh complete")
    except Exception as e:
        print(f"[SCHEDULER] institutional refresh failed: {e}")


def _macro_job():
    print("[SCHEDULER] macro FII/DII fetch started")
    try:
        import macro

        macro.refresh()
        print("[SCHEDULER] macro fetch complete")
    except Exception as e:
        print(f"[SCHEDULER] macro fetch failed: {e}")


def _fundamentals_job():
    print("[SCHEDULER] weekly fundamentals refresh started")
    try:
        import fundamentals_refresh

        fundamentals_refresh.auto()
        print("[SCHEDULER] weekly fundamentals refresh complete")
    except Exception as e:
        print(f"[SCHEDULER] fundamentals refresh failed: {e}")


def _retrain_job():
    print("[SCHEDULER] weekly meta retrain started")
    try:
        import meta_model

        meta_model.train()
        meta_model._MODEL = None
        print("[SCHEDULER] weekly meta retrain complete")
    except Exception as e:
        print(f"[SCHEDULER] retrain failed: {e}")


def _validate_mc_job():
    print("[SCHEDULER] weekly monte-carlo started")
    try:
        import validate

        validate.run_mode("mc")
        print("[SCHEDULER] monte-carlo complete")
    except Exception as e:
        print(f"[SCHEDULER] monte-carlo failed: {e}")


def _validate_wf_job():
    print("[SCHEDULER] monthly walk-forward started")
    try:
        import validate

        validate.run_mode("wf")
        print("[SCHEDULER] walk-forward complete")
    except Exception as e:
        print(f"[SCHEDULER] walk-forward failed: {e}")


def _drift_check():
    try:
        import db

        conn = db.get_conn()
        rows = conn.execute(
            "SELECT outcome FROM swing_signals WHERE outcome IN ('WIN','LOSS') ORDER BY signal_date DESC LIMIT 40"
        ).fetchall()
        conn.close()
        if len(rows) < 15:
            print("[DRIFT] not enough graded trades yet")
            return
        wins = sum(1 for r in rows if r[0] == "WIN")
        live_wr = wins / len(rows)
        if live_wr < 0.35:
            msg = f"[DRIFT] ⚠️ live win-rate {live_wr:.0%} over last {len(rows)} graded — review setup quality"
            print(msg)
            try:
                import swing_alerts

                swing_alerts.send(msg)
            except Exception:
                pass
        else:
            print(f"[DRIFT] ok — live win-rate {live_wr:.0%} ({len(rows)} graded)")
    except Exception as e:
        print(f"[DRIFT] check skipped: {e}")


def start():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=IST)
    _scheduler.add_job(
        _data_quality_job, CronTrigger(hour=15, minute=30, timezone=IST), id="data_quality", replace_existing=True
    )
    _scheduler.add_job(
        _daily_job, CronTrigger(hour=15, minute=45, timezone=IST), id="daily_update", replace_existing=True
    )
    _scheduler.add_job(
        _swing_job, CronTrigger(hour=16, minute=15, timezone=IST), id="swing_scan", replace_existing=True
    )
    _scheduler.add_job(
        _institutional_job, CronTrigger(hour=16, minute=45, timezone=IST), id="institutional", replace_existing=True
    )
    _scheduler.add_job(
        _macro_job, CronTrigger(hour=17, minute=30, timezone=IST), id="macro_flow", replace_existing=True
    )
    _scheduler.add_job(
        _fundamentals_job,
        CronTrigger(day_of_week="sat", hour=8, minute=0, timezone=IST),
        id="fundamentals_refresh",
        replace_existing=True,
    )
    _scheduler.add_job(
        _retrain_job,
        CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=IST),
        id="meta_retrain",
        replace_existing=True,
    )
    _scheduler.add_job(
        _validate_mc_job,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=IST),
        id="validate_mc",
        replace_existing=True,
    )
    _scheduler.add_job(
        _validate_wf_job, CronTrigger(day=1, hour=10, minute=0, timezone=IST), id="validate_wf", replace_existing=True
    )
    _scheduler.start()
    print(
        "[SCHEDULER] started — dq@15:30, daily@15:45, swing@16:15, "
        "inst@16:45, macro@17:30, fund@Sat08:00, retrain@Sat09:00, "
        "mc@Mon08:00, wf@1st10:00 IST"
    )


def stop():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
