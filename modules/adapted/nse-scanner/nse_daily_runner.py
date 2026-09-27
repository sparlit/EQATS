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
nse_daily_runner.py — Master Automation Script (v3 — Rolling 180-day window)
=============================================================================
WHAT CHANGED FROM v2:

  1. HOLIDAY CHECK (new Step 0)
     - If today is NSE holiday OR Saturday/Sunday → skip everything
     - Logs "Holiday — no scan" and exits cleanly
     - Uses the same NSE_HOLIDAYS list as before

  2. TODAY-ONLY DOWNLOAD (Step 1 changed)
     - OLD: downloaded last 90 days every run (wasteful)
     - NEW: downloads yesterday's closing data only (3 files, seconds)
     - NSE publishes previous day's data → we run at 6 AM IST next morning
     - So "today's download" = yesterday's trading session files

  3. ROLLING WINDOW TRIM (new Step after Load)
     - After loading yesterday's data → DB has 181 days
     - trim_to_180_days() deletes the oldest day
     - DB stays at exactly 180 days always

  4. AUTO-CLEANUP OLD DATA (Step 0, unchanged)
     - Still runs auto_cleanup_nse_data for raw CSV files
     - Keeps raw CSVs for 7 days, deletes older ones

Pipeline flow:
    Step 0a — Holiday / Weekend check   → EXIT if holiday
    Step 0b — Auto-cleanup raw CSVs
    Step 1  — Download yesterday's data (3 files only)
    Step 2  — Load into SQLite DB
    Step 2b — Trim DB to 180 days (delete oldest day)
    Step 3  — Scan stocks (reads 180 days from DB)
    Step 4  — Collect news (shortlist only)
    Step 5  — Enrich with news flags
    Step 6  — Output: Excel + Telegram

Usage:
    python nse_daily_runner.py
    python nse_daily_runner.py --date 05-03-2026
    python nse_daily_runner.py --dry-run
    python nse_daily_runner.py --skip-download
    python nse_daily_runner.py --skip-news
    python nse_daily_runner.py --force-holiday  (override holiday check)

Windows Task Scheduler / Railway Cron:
    Schedule: Weekdays 6:00 AM IST (00:30 UTC)
"""

import argparse
import logging
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from time import time

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    sys.exit(1)

# ── NSE Holiday list (update annually) ────────────────────────────────────
NSE_HOLIDAYS = {
    # 2025
    date(2025, 1, 26),
    date(2025, 2, 26),
    date(2025, 3, 14),
    date(2025, 4, 10),
    date(2025, 4, 14),
    date(2025, 4, 18),
    date(2025, 5, 1),
    date(2025, 8, 15),
    date(2025, 8, 27),
    date(2025, 10, 2),
    date(2025, 10, 21),
    date(2025, 10, 22),
    date(2025, 11, 5),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 26),
    date(2026, 3, 25),
    date(2026, 4, 2),
    date(2026, 4, 10),
    date(2026, 4, 14),
    date(2026, 5, 1),
    date(2026, 8, 15),
    date(2026, 10, 2),
    date(2026, 10, 22),
    date(2026, 11, 5),
    date(2026, 12, 25),
}

KEEP_HISTORICAL_DAYS = 180


# ═══════════════════════════════════════════════════════════════════════════
# TRADING DAY HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def is_trading_day(d: date) -> bool:
    """Returns True if d is a valid NSE trading day."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d in NSE_HOLIDAYS:
        return False
    return True


def get_last_trading_day(from_date: date | None = None) -> date:
    """Returns the most recent trading day on or before from_date."""
    d = from_date or date.today()
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def get_previous_trading_day(from_date: date | None = None) -> date:
    """
    Returns the trading day BEFORE from_date.
    This is the data we need to download — yesterday's closing data.
    """
    d = (from_date or date.today()) - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


# ═══════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════

os.makedirs(config.LOG_DIR, exist_ok=True)
log_file = os.path.join(config.LOG_DIR, "daily_runner.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# STEP RUNNER
# ═══════════════════════════════════════════════════════════════════════════


def run_step(step_num: int, name: str, fn, *args, **kwargs):
    """Run one pipeline step with timing and error handling."""
    print(f"\n{'=' * 56}")
    print(f"  Step {step_num}: {name}")
    print(f"{'=' * 56}")
    log.info(f"Starting Step {step_num}: {name}")

    t0 = time()
    try:
        result = fn(*args, **kwargs)
        elapsed = round(time() - t0, 1)
        print(f"  Done in {elapsed}s")
        log.info(f"Step {step_num} OK ({elapsed}s)")
        return True, result, elapsed
    except Exception as e:
        elapsed = round(time() - t0, 1)
        print(f"  FAILED: {e}")
        log.exception(f"Step {step_num} FAILED: {name} — {e}")
        log.exception(traceback.format_exc())
        return False, None, elapsed


# ═══════════════════════════════════════════════════════════════════════════
# STEP 0a — HOLIDAY / WEEKEND CHECK
# ═══════════════════════════════════════════════════════════════════════════


def check_trading_day(today: date, force: bool = False) -> tuple:
    """
    Check if today is a valid trading day.

    Returns:
        (should_run: bool, data_date: date, reason: str)

    should_run = False → skip the entire pipeline
    data_date  = the date whose data we need to download (yesterday)
    reason     = human-readable explanation
    """
    if force:
        data_date = get_previous_trading_day(today)
        return True, data_date, f"Force override — using data date {data_date}"

    # Weekend check
    if today.weekday() >= 5:
        day_name = "Saturday" if today.weekday() == 5 else "Sunday"
        return False, None, f"Weekend ({day_name}) — NSE closed, no scan"

    # Holiday check
    if today in NSE_HOLIDAYS:
        return False, None, f"NSE Holiday ({today}) — market closed, no scan"

    # Valid trading day — get yesterday's data
    data_date = get_previous_trading_day(today)

    # Edge case: if yesterday was also a holiday, warn
    days_back = (today - data_date).days
    if days_back > 1:
        reason = f"Today is trading day. Downloading data for {data_date} ({days_back} days ago — previous session)"
    else:
        reason = f"Today is trading day. Downloading data for {data_date}"

    return True, data_date, reason


# ═══════════════════════════════════════════════════════════════════════════
# STEP 0b — AUTO-CLEANUP RAW CSVs
# ═══════════════════════════════════════════════════════════════════════════


def step_cleanup() -> dict:
    """Auto-cleanup raw NSE CSV files older than 7 days."""
    try:
        from auto_cleanup_nse_data import cleanup_old_data

        deleted, freed, remaining = cleanup_old_data(keep_days=KEEP_HISTORICAL_DAYS, dry_run=False)
        print(f"  Deleted: {deleted} month(s) | Freed: {freed:.2f} MB | Remaining: {remaining} files")
        return {"deleted": deleted, "freed_mb": freed, "remaining": remaining}
    except ImportError:
        print("  auto_cleanup_nse_data not found — skipping CSV cleanup")
        return {"deleted": 0, "freed_mb": 0, "remaining": 0}


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — DOWNLOAD (today-only — yesterday's closing data)
# ═══════════════════════════════════════════════════════════════════════════


def step_download(data_date: date) -> bool:
    """
    Download yesterday's NSE closing data — 3 files only.

    Files downloaded:
      sec_bhavdata_full_{DDMMYYYY}.csv   — OHLCV + delivery for all EQ stocks
      REG_IND{DDMMYYYY}.csv             — regulatory blacklist
      ind_close_all_{DDMMYYYY}.csv      — all index closes

    This is all the scanner needs. Bundle files (CMVOLT, PE, 52W)
    are optional and only needed for initial historical load.
    """
    from nse_historical_downloader import download_direct

    result = download_direct(data_date)
    print(f"  Downloaded {result} file(s) for {data_date.strftime('%d-%b-%Y')}")

    if result == 0:
        print(f"  ⚠️  No files downloaded for {data_date}")
        print("      This can happen if NSE hasn't published yet.")
        print("      Will try to load from existing files.")

    return True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — LOAD + ROLLING WINDOW TRIM
# ═══════════════════════════════════════════════════════════════════════════


def step_load(data_date: date) -> dict:
    """
    Load downloaded files into SQLite DB, then trim to 180 days.

    Flow:
      1. Load data_date → DB has N+1 days
      2. trim_to_180_days() → DB back to 180 days
    """
    from nse_loader import init_database, load_day, trim_to_180_days

    init_database()

    # Load yesterday's data
    result = load_day(data_date, do_cleanup=False)
    total = sum(result["rows"].values())
    print(f"  Loaded: {total} rows | status={result['status']}")

    if result["status"] not in ("ok", "already_loaded", "partial"):
        msg = f"Load failed for {data_date}: status={result['status']}"
        raise ValueError(msg)

    # Trim to rolling 180-day window
    print(f"\n  Trimming to {KEEP_HISTORICAL_DAYS} days rolling window...")
    trim_to_180_days(keep_days=KEEP_HISTORICAL_DAYS)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — SCAN
# ═══════════════════════════════════════════════════════════════════════════


def step_scan(scan_date: date):
    """
    Run forward-probability scanner.
    scan_date = the data date (yesterday's closing = today's scan basis)
    """
    from nse_scanner import scan_stocks

    results = scan_stocks(scan_date=scan_date)

    if results.empty:
        msg = "Scanner returned no results"
        raise ValueError(msg)

    hc = wl = 0
    if "conviction" in results.columns:
        hc = (results["conviction"] == "HIGH CONVICTION").sum()
        wl = (results["conviction"] == "Watchlist").sum()

    print(f"  Total  : {len(results)} stocks")
    print(f"  HC     : {hc} HIGH CONVICTION")
    print(f"  WL     : {wl} Watchlist")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — NEWS (shortlist only, no re-scan)
# ═══════════════════════════════════════════════════════════════════════════


def step_news(scan_results, scan_date: date) -> dict:
    """Collect news for HC + Watchlist stocks only. Caps at 15 stocks."""
    from nse_news_collector import get_news_for_stocks, save_news

    if "conviction" in scan_results.columns:
        shortlist_df = scan_results[scan_results["conviction"].isin(["HIGH CONVICTION", "Watchlist"])]
        shortlist = shortlist_df["symbol"].tolist()
    else:
        shortlist = scan_results.head(10)["symbol"].tolist()

    shortlist = shortlist[:15]

    if not shortlist:
        print("  No HC/Watchlist stocks to collect news for")
        return {}

    print(f"  Collecting news for {len(shortlist)} stocks")
    news = get_news_for_stocks(shortlist, days=30)
    save_news(news, scan_date)

    stocks_with_news = sum(1 for v in news.values() if v.get("has_news"))
    stocks_with_flags = sum(1 for v in news.values() if v.get("flags"))
    print(f"  With news : {stocks_with_news}/{len(shortlist)}")
    print(f"  With flags: {stocks_with_flags}/{len(shortlist)}")

    return news


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 — ENRICH
# ═══════════════════════════════════════════════════════════════════════════


def step_enrich(scan_results, news_data: dict):
    """Merge news intelligence into scanner DataFrame."""
    from nse_news_collector import enrich_scanner_results

    if not news_data:
        print("  No news data — skipping enrichment")
        return scan_results

    enriched = enrich_scanner_results(scan_results, news_data)
    risk_count = enriched["has_risk"].sum() if "has_risk" in enriched.columns else 0
    enriched_count = enriched["news_tone"].notna().sum() if "news_tone" in enriched.columns else 0

    print(f"  Enriched: {enriched_count} stocks with news context")
    if risk_count:
        risk_stocks = enriched[enriched["has_risk"]]["symbol"].tolist()
        print(f"  ⚠️  {risk_count} stocks with risk flags: {', '.join(risk_stocks)}")

    return enriched


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 — OUTPUT
# ═══════════════════════════════════════════════════════════════════════════


def step_output(results, scan_date: date, dry_run: bool = False) -> dict:
    """Generate Excel and send Telegram."""
    from nse_output import save_excel, send_telegram

    excel_file = save_excel(results, scan_date)
    if excel_file:
        print(f"  Excel: {os.path.basename(excel_file)}")

    if dry_run:
        print("  Telegram: SKIPPED (dry-run mode)")
        tg_sent = False
    else:
        tg_sent = send_telegram(results, scan_date)
        print(f"  Telegram: {'sent ✅' if tg_sent else 'failed ❌'}")

    return {"excel": excel_file, "telegram": tg_sent}


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY PRINTER
# ═══════════════════════════════════════════════════════════════════════════


def print_summary(today: date, data_date: date, steps: list, total_time: float):
    print(f"\n{'#' * 56}")
    print("  NSE DAILY RUNNER — COMPLETE")
    print(f"  Run date  : {today.strftime('%d-%b-%Y')}")
    print(f"  Data date : {data_date.strftime('%d-%b-%Y')} (yesterday)")
    print(f"  Time      : {total_time:.1f}s")
    print(f"{'─' * 56}")

    for num, name, ok, elapsed in steps:
        status = "OK  " if ok else "FAIL"
        print(f"  Step {num}  [{status}]  {name:<35} {elapsed:.1f}s")

    all_ok = all(ok for _, _, ok, _ in steps)
    print(f"{'─' * 56}")
    print(f"  Result : {'✅ SUCCESS' if all_ok else '⚠️  COMPLETED WITH ERRORS'}")
    print(f"  Log    : {log_file}")
    print(f"{'#' * 56}\n")

    log.info(
        f"Pipeline done: run={today} data={data_date} time={total_time:.1f}s status={'OK' if all_ok else 'ERRORS'}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════


def run_pipeline(
    today: date | None = None,
    skip_download: bool = False,
    skip_news: bool = False,
    dry_run: bool = False,
    force_holiday: bool = False,
) -> bool:
    """
    Run complete daily pipeline.

    today         = date the runner is executing (default: date.today())
    skip_download = skip download step (use existing files)
    skip_news     = skip news collection
    dry_run       = run all steps but skip Telegram send
    force_holiday = override holiday check (for testing)
    """
    if today is None:
        today = date.today()

    t0 = time()
    steps_log = []

    # ── Step 0a: Holiday / Weekend check ──────────────────────────────────
    should_run, data_date, reason = check_trading_day(today, force=force_holiday)

    print(f"\n{'#' * 56}")
    print("  NSE DAILY RUNNER v3")
    print(f"  Run date  : {today.strftime('%d-%b-%Y (%A)')}")
    print(f"  Status    : {reason}")
    print(f"  Mode      : {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'#' * 56}")

    if not should_run:
        print(f"\n  ⏭️  SKIPPING — {reason}")
        print("  No data to process. Pipeline complete.\n")
        log.info(f"Pipeline skipped: {reason}")
        return True  # not an error — expected skip

    print(f"\n  📅 Will download data for: {data_date.strftime('%d-%b-%Y')} (previous session)")

    scan_results = None
    news_data = {}

    # ── Step 0b: Auto-cleanup CSVs ────────────────────────────────────────
    ok, _, elapsed = run_step(0, "Auto-cleanup raw CSVs", step_cleanup)
    steps_log.append((0, "Auto-cleanup", ok, elapsed))
    if not ok:
        print("  ⚠️  Cleanup failed — continuing anyway")

    # ── Step 1: Download yesterday's data (3 files only) ──────────────────
    if not skip_download:
        ok, _, elapsed = run_step(1, f"Download {data_date.strftime('%d-%b-%Y')} data", step_download, data_date)
        steps_log.append((1, "Download (today only)", ok, elapsed))
        if not ok:
            print("  ⚠️  Download failed — will try existing files")
    else:
        print("\n  Step 1: Download — SKIPPED (--skip-download)")
        steps_log.append((1, "Download (skipped)", True, 0.0))

    # ── Step 2: Load + trim rolling window ────────────────────────────────
    ok, _, elapsed = run_step(2, "Load into DB + trim to 180 days", step_load, data_date)
    steps_log.append((2, "Load + Trim 180d", ok, elapsed))
    if not ok:
        print("  ❌ DB load failed — cannot continue")
        print_summary(today, data_date, steps_log, time() - t0)
        return False

    # ── Step 3: Scan ──────────────────────────────────────────────────────
    ok, scan_results, elapsed = run_step(3, "Scan stocks (forward score)", step_scan, data_date)
    steps_log.append((3, "Scan", ok, elapsed))
    if not ok or scan_results is None or scan_results.empty:
        print("  ❌ Scan failed — cannot continue")
        print_summary(today, data_date, steps_log, time() - t0)
        return False

    # ── Step 4: News ──────────────────────────────────────────────────────
    if not skip_news:
        ok, news_data, elapsed = run_step(4, "Collect news (shortlist only)", step_news, scan_results, data_date)
        steps_log.append((4, "News", ok, elapsed))
        if not ok:
            news_data = {}
            print("  ⚠️  News failed — continuing without news")
    else:
        print("\n  Step 4: News — SKIPPED (--skip-news)")
        steps_log.append((4, "News (skipped)", True, 0.0))

    # ── Step 5: Enrich ────────────────────────────────────────────────────
    ok, enriched, elapsed = run_step(5, "Enrich with news flags", step_enrich, scan_results, news_data)
    steps_log.append((5, "Enrich", ok, elapsed))
    final_results = enriched if (ok and enriched is not None) else scan_results

    # ── Step 6: Output ────────────────────────────────────────────────────
    ok, _, elapsed = run_step(6, "Excel + Telegram", step_output, final_results, data_date, dry_run)
    steps_log.append((6, "Output", ok, elapsed))

    # ── Summary ───────────────────────────────────────────────────────────
    print_summary(today, data_date, steps_log, time() - t0)
    return True


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="NSE Daily Runner v3 — Rolling 180-day window",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nse_daily_runner.py                    # normal daily run
  python nse_daily_runner.py --dry-run          # no Telegram send
  python nse_daily_runner.py --skip-download    # use existing files
  python nse_daily_runner.py --skip-news        # skip news collection
  python nse_daily_runner.py --date 05-03-2026  # run for specific date
  python nse_daily_runner.py --force-holiday    # run even on holiday

Railway Cron:
  Schedule: 0 0 30 * * 1-5  (6:00 AM IST = 00:30 UTC, weekdays)
  Command : python nse_daily_runner.py
        """,
    )

    parser.add_argument("--date", type=str, help="Run date DD-MM-YYYY (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Run all steps but skip Telegram")
    parser.add_argument("--skip-download", action="store_true", help="Skip download — use existing files")
    parser.add_argument("--skip-news", action="store_true", help="Skip news collection")
    parser.add_argument("--force-holiday", action="store_true", help="Override holiday check (for testing)")

    args = parser.parse_args()

    # Parse run date
    today = date.today()
    if args.date:
        today = None
        for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]:
            try:
                today = datetime.strptime(args.date, fmt).date()
                break
            except ValueError:
                pass
        if not today:
            print(f"Invalid date: {args.date}. Use DD-MM-YYYY")
            sys.exit(1)

    success = run_pipeline(
        today=today,
        skip_download=args.skip_download,
        skip_news=args.skip_news,
        dry_run=args.dry_run,
        force_holiday=args.force_holiday,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
