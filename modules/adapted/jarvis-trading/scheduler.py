"""
AXIOM Scheduler — APScheduler background worker.
Runs:
  08:30 IST  — Morning briefing PDF + email + Telegram
  09:15 IST  — Pre-market task list (Telegram)
  09:30–15:15 — Intraday 15-min scanner every 5 min (Telegram alerts)
  13:00 IST  — Midday 15-min scan summary (Telegram)
  15:35 IST  — Post-market checklist PDF + email + Telegram
Start with: python scheduler.py
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

from ai.brain import generate_market_briefing, generate_task_list
from data.fetcher import load_universe
from data.market_context import build_briefing_context
from monitors.intraday_monitor import make_monitor_from_watchlist
from monitors.telegram_bot import send_briefing, send_document, send_message, send_regime_alert
from reports.pdf_generator import generate_text_report
from screener.regime_classifier import classify_regime
from screener.screener import run_screener

IST = ZoneInfo("Asia/Kolkata")
REPORTS_DIR = Path("data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# NSE trading holidays by year. Add a new year's set each December.
NSE_HOLIDAYS: dict[int, set] = {
    2026: {
        date(2026, 1, 26),
        date(2026, 3, 25),
        date(2026, 4, 2),
        date(2026, 4, 10),
        date(2026, 4, 14),
        date(2026, 5, 1),
        date(2026, 8, 15),
        date(2026, 10, 2),
        date(2026, 11, 4),
        date(2026, 12, 25),
    },
}

# Backward-compat alias
NSE_HOLIDAYS_2026 = NSE_HOLIDAYS[2026]


def is_market_day() -> bool:
    today = datetime.now(IST).date()
    if today.weekday() >= 5:
        logger.info("Market closed — weekend")
        return False
    holidays = NSE_HOLIDAYS.get(today.year)
    if holidays is None:
        # No calendar for this year yet — fail safe: still run, but warn loudly
        logger.warning("No NSE holiday calendar for {} — update NSE_HOLIDAYS in scheduler.py", today.year)
    elif today in holidays:
        logger.info("Market closed — NSE holiday: {}", today)
        return False
    return True


# ─────────────────────────────────────────────────────────────────
# 08:30 AM — MORNING BRIEFING
# ─────────────────────────────────────────────────────────────────

def run_morning_briefing() -> None:
    if not is_market_day():
        return
    logger.info("=== MORNING BRIEFING PIPELINE START ===")
    try:
        universe = load_universe()
        regime   = classify_regime()
        context  = build_briefing_context()
        context.update({
            "symbol_count":    len(universe),
            "watchlist_count": min(10, len(universe)),
            "regime":          regime.regime,
            "nifty_close":     regime.nifty_close,
            "adx":             regime.adx_value,
        })

        try:
            screener_df = run_screener(None)
            if not screener_df.empty:
                top_picks = screener_df[screener_df["grade"].isin(["A", "B"])].head(5)
                context["top_picks"] = top_picks[
                    [c for c in ["symbol", "score", "grade", "rs_20d", "rs_60d", "close"] if c in top_picks.columns]
                ].to_dict("records")
                logger.info("Screener: {} Grade A/B picks for briefing", len(top_picks))
                # Persist watchlist to committed CSV so the serverless intraday
                # scanner has something to scan (DB is ephemeral on CI runners)
                try:
                    from storage.watchlist_csv import save_watchlist_from_screener
                    save_watchlist_from_screener(screener_df, max_symbols=15)
                except Exception as exc:
                    logger.warning("Watchlist CSV save skipped: {}", exc)
        except Exception as exc:
            logger.warning("Screener skipped: {}", exc)
            context["top_picks"] = []

        briefing_text = generate_market_briefing(context)
        if not briefing_text:
            logger.error("Briefing text empty — aborting")
            return

        # PDF
        date_str = datetime.now(IST).date().strftime("%d %b %Y")
        pdf_path = REPORTS_DIR / f"briefing_{datetime.now(IST).date()}.pdf"
        generate_text_report("AXIOM Morning Briefing", briefing_text, pdf_path)

        # Telegram — briefing text + regime + PDF document
        send_briefing(briefing_text, date_str)
        send_regime_alert(regime.regime, regime.nifty_close, regime.adx_value)
        ok, err = send_document(pdf_path, caption=f"📊 <b>AXIOM Morning Briefing — {date_str}</b> | Regime: {regime.regime}")
        if ok:
            logger.success("Morning briefing PDF sent to Telegram: {}", pdf_path.name)
        else:
            logger.error("Briefing PDF Telegram send failed: {}", err)

        # Telegram — top picks summary
        if context.get("top_picks"):
            picks_lines = "\n".join(
                f"  {p['symbol']} — Score {p.get('score','?')} [{p.get('grade','?')}] ₹{p.get('close','?')}"
                for p in context["top_picks"]
            )
            send_message(f"<b>AXIOM Top Picks</b>\n{picks_lines}")

        logger.success("=== MORNING BRIEFING DONE ===")
    except Exception as exc:
        logger.exception("Morning briefing failed: {}", exc)


# ─────────────────────────────────────────────────────────────────
# 09:15 AM — PRE-MARKET TASK LIST
# ─────────────────────────────────────────────────────────────────

def run_premarket_tasks() -> None:
    if not is_market_day():
        return
    logger.info("=== PRE-MARKET TASKS PIPELINE START ===")
    try:
        regime = classify_regime()
        universe = load_universe()
        checklist = generate_task_list({
            "session":       "pre-market",
            "symbol_count":  len(universe),
            "market":        "NSE",
            "time":          "09:15 IST",
            "regime":        regime.regime,
            "nifty_close":   regime.nifty_close,
        })

        # PDF
        date_str = datetime.now(IST).date().strftime("%d %b %Y")
        pdf_path = REPORTS_DIR / f"premarket_tasks_{datetime.now(IST).date()}.pdf"
        generate_text_report("AXIOM Pre-Market Tasks", checklist, pdf_path)

        # Telegram — text + PDF document
        send_message(
            f"<b>AXIOM Pre-Market Checklist — {date_str}</b>\n"
            f"Regime: <b>{regime.regime}</b> · Nifty: {regime.nifty_close:,.0f}\n\n"
            + checklist[:2000]
        )
        ok, err = send_document(pdf_path, caption=f"📋 <b>AXIOM Pre-Market Checklist — {date_str}</b>")
        logger.success("Pre-market tasks sent") if ok else logger.error("Pre-market PDF Telegram send failed: {}", err)
    except Exception as exc:
        logger.exception("Pre-market task pipeline failed: {}", exc)


# ─────────────────────────────────────────────────────────────────
# 15:35 PM — POST-MARKET CHECKLIST
# ─────────────────────────────────────────────────────────────────

def run_post_market_summary() -> None:
    if not is_market_day():
        return
    logger.info("=== POST-MARKET SUMMARY PIPELINE START ===")
    try:
        universe = load_universe()
        checklist = generate_task_list({
            "session":      "post-market",
            "symbol_count": len(universe),
            "market":       "NSE",
            "time":         "15:35 IST",
        })

        # PDF
        date_str = datetime.now(IST).date().strftime("%d %b %Y")
        pdf_path = REPORTS_DIR / f"post_market_{datetime.now(IST).date()}.pdf"
        generate_text_report("AXIOM Post-Market Checklist", checklist, pdf_path)

        # Telegram — text + PDF document
        send_message(
            f"<b>AXIOM Post-Market Checklist — {date_str}</b>\n\n"
            + checklist[:2000]
        )
        ok, err = send_document(pdf_path, caption=f"📋 <b>AXIOM Post-Market Checklist — {date_str}</b>")
        if not ok:
            logger.error("Post-market PDF Telegram send failed: {}", err)
        logger.success("Post-market checklist sent")
    except Exception as exc:
        logger.exception("Post-market summary failed: {}", exc)


# ─────────────────────────────────────────────────────────────────
# INTRADAY 15-MIN SCANNER
# ─────────────────────────────────────────────────────────────────

_monitor: object | None = None


def _get_monitor():
    global _monitor
    if _monitor is None:
        _monitor = make_monitor_from_watchlist()
    return _monitor


def _run_intraday_scan() -> None:
    """Every 5 min scan — fires per-stock alerts on new signals."""
    if not is_market_day():
        return
    mon = _get_monitor()
    try:
        mon.scan_once()
    except Exception as exc:
        logger.exception("Intraday scan tick failed: {}", exc)


def _run_midday_summary() -> None:
    """1 PM — send a summary of all active signals on Telegram."""
    if not is_market_day():
        return
    mon = _get_monitor()
    results = getattr(mon, "scan_results", {})
    if not results:
        return
    hits = {s: d for s, d in results.items() if d.get("signals")}
    now_str = datetime.now(IST).strftime("%H:%M IST")
    if hits:
        lines = "\n".join(
            f"  {sym} — {', '.join(d['signals'])} | ₹{d.get('close', 0):,.0f} RSI:{d.get('rsi', '?')} ADX:{d.get('adx', '?')}"
            for sym, d in hits.items()
        )
        send_message(
            f"<b>AXIOM Midday Signal Summary — {now_str}</b>\n"
            f"{len(hits)} active signal(s):\n{lines}"
        )
    else:
        send_message(f"<b>AXIOM Midday — {now_str}</b>\nNo active signals on watchlist.")


# ─────────────────────────────────────────────────────────────────
# SCHEDULER ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(
        run_morning_briefing,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30, timezone=IST),
        id="morning_briefing", replace_existing=True,
    )
    scheduler.add_job(
        run_premarket_tasks,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=15, timezone=IST),
        id="premarket_tasks", replace_existing=True,
    )
    scheduler.add_job(
        _run_intraday_scan,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="30,35,40,45,50,55,0,5,10,15",
            timezone=IST,
        ),
        id="intraday_monitor", replace_existing=True,
    )
    scheduler.add_job(
        _run_midday_summary,
        CronTrigger(day_of_week="mon-fri", hour=13, minute=0, timezone=IST),
        id="midday_summary", replace_existing=True,
    )
    scheduler.add_job(
        run_post_market_summary,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone=IST),
        id="post_market_summary", replace_existing=True,
    )

    logger.info("AXIOM Scheduler started")
    logger.info("  08:30  Morning briefing   — PDF + Email + Telegram")
    logger.info("  09:15  Pre-market tasks   — PDF + Email + Telegram")
    logger.info("  09:30–15:15  15-min scan  — Telegram alerts every 5 min")
    logger.info("  13:00  Midday summary     — Telegram signal digest")
    logger.info("  15:35  Post-market tasks  — PDF + Email + Telegram")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    start_scheduler()
