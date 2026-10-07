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


#!/usr/bin/env python3
"""Master platform scheduler — runs as a persistent daemon.

Schedule (IST, Mon-Fri):
    08:00       Morning start:   MCP + web + announcements backfill
    08:00–16:00 Market hours:    30-min data refresh, 15-min Redis warm
    16:00       Market close:    Stop heavy background jobs, keep web alive
    18:00       Evening cycle:   Full ingestion + signals + suggestions + cache
    18:00–21:00 Evening session: Web alive, 30-min Redis warm
    21:00       Night stop:      Stop everything cleanly

Weekends: no active trading, but web stays available for research.

Usage:
    python scripts/platform_scheduler.py          # Run in foreground
    python scripts/platform_scheduler.py --daemon  # Fork to background (nohup)
"""


import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("platform_scheduler")

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
LOG_DIR = ROOT / "logs"
TZ_IST = timezone(timedelta(hours=5, minutes=30))

_running = True


def _now_ist() -> datetime:
    return datetime.now(TZ_IST)


def _weekday() -> bool:
    return _now_ist().weekday() < 5  # Mon=0 .. Fri=4


def _run(name: str, cmd: list[str], timeout: int = 600, check: bool = False) -> int:
    """Run a command with logging. Returns exit code."""
    log.info(f"START  {name}: {' '.join(cmd)}")
    try:
        r = subprocess.run(
            cmd,
            cwd=str(ROOT),
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        if r.stdout.strip():
            for line in r.stdout.strip().split("\n")[-5:]:
                log.info(f"  {name}: {line}")
        if r.stderr.strip():
            for line in r.stderr.strip().split("\n")[-3:]:
                log.warning(f"  {name} stderr: {line}")
        if check and r.returncode != 0:
            log.error(f"FAIL   {name} exit={r.returncode}")
        return r.returncode
    except subprocess.TimeoutExpired:
        log.error(f"TIMEOUT {name} after {timeout}s")
        return -1
    except Exception as e:
        log.error(f"ERROR  {name}: {e}")
        return -1


def _port_open(port: int) -> bool:
    try:
        with __import__("socket").create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def _pgrep(pattern: str) -> bool:
    try:
        r = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# ── Actions ────────────────────────────────────────────────────────────────


def start_mcp() -> None:
    if _pgrep("nse-bse-mcp"):
        log.info("MCP already running")
        return
    log.info("Starting MCP server...")
    subprocess.Popen(
        ["npx", "-y", "nse-bse-mcp"],
        stdout=open(LOG_DIR / "mcp.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(3)
    if _port_open(3000):
        log.info("MCP started on port 3000")
    else:
        log.warning(f"MCP may not have started — check {LOG_DIR}/mcp.log")


def start_web() -> None:
    if _port_open(8080):
        log.info("Web already running on 8080")
        return
    log.info("Starting web dashboard...")
    subprocess.Popen(
        [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "indian_quant.web.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        stdout=open(LOG_DIR / "web.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(3)
    if _port_open(8080):
        log.info("Web started on port 8080")
    else:
        log.warning(f"Web may not have started — check {LOG_DIR}/web.log")


def stop_web() -> None:
    if not _port_open(8080):
        return
    log.info("Stopping web on port 8080...")
    subprocess.run(["fuser", "-k", "8080/tcp"], capture_output=True, timeout=5)
    time.sleep(1)


def stop_heavy() -> None:
    """Stop background ingestion/signals but keep web alive."""
    for proc in [
        "announcements_backfill",
        "bulk_ingest",
        "daily_signals",
        "paper_track",
        "suggestion_manager",
        "cache_signals",
    ]:
        if _pgrep(proc):
            log.info(f"Stopping {proc}...")
            subprocess.run(["pkill", "-f", proc], capture_output=True, timeout=5)


def stop_all() -> None:
    stop_heavy()
    stop_web()
    if _pgrep("nse-bse-mcp"):
        log.info("Stopping MCP...")
        subprocess.run(["pkill", "-f", "nse-bse-mcp"], capture_output=True, timeout=5)
        time.sleep(2)


def morning_start() -> None:
    """08:00 IST — Start everything for the trading day."""
    log.info("═══ MORNING START (08:00 IST) ═══")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    start_mcp()
    start_web()
    # Announcements backfill (non-blocking)
    if not _pgrep("announcements_backfill"):
        subprocess.Popen(
            [str(VENV_PYTHON), "scripts/announcements_backfill.py", "--from", "2024-01-01"],
            cwd=str(ROOT),
            stdout=open(LOG_DIR / "backfill.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.info("Announcements backfill started")


def market_hours_refresh() -> None:
    """Every 30 min during 08:30–15:30 IST — quick data refresh."""
    if not _weekday():
        return
    log.info("═══ MARKET HOURS REFRESH ═══")
    _run("quick_signals", [str(VENV_PYTHON), "scripts/daily_signals.py"], timeout=120)
    _run("cache_rebuild", [str(VENV_PYTHON), "scripts/cache_signals.py"], timeout=120)
    # Live mark-to-market + stop/target settlement for open paper positions
    _run("live_paper_update", [str(VENV_PYTHON), "scripts/live_paper_update.py"], timeout=120)


def market_close() -> None:
    """16:00 IST — Stop heavy background jobs, settle hypothesis trades."""
    log.info("═══ MARKET CLOSE (16:00 IST) ═══")
    _run("live_paper_update", [str(VENV_PYTHON), "scripts/live_paper_update.py"], timeout=120)
    _run("hypothesis_settle", [str(VENV_PYTHON), "scripts/hypothesis_settle.py"], timeout=300)
    stop_heavy()
    log.info("Heavy jobs stopped. Web stays alive.")


def evening_cycle() -> None:
    """18:00 IST — Full data pipeline after NSE publishes bhavcopy."""
    if not _weekday():
        return
    log.info("═══ EVENING CYCLE (18:00 IST) ═══")
    today = _now_ist().strftime("%Y-%m-%d")
    _run(
        "bulk_ingest",
        [
            str(VENV_PYTHON),
            "scripts/bulk_ingest.py",
            "--from",
            today,
            "--to",
            today,
            "--exchange",
            "both",
            "--delivery-only",
        ],
        timeout=900,
    )
    _run("daily_signals", [str(VENV_PYTHON), "scripts/daily_signals.py"], timeout=180)
    _run("paper_settle", [str(VENV_PYTHON), "scripts/paper_track.py", "settle"], timeout=60)
    _run(
        "paper_snapshot",
        [str(VENV_PYTHON), "scripts/paper_track.py", "snapshot", "--capital", "250000"],
        timeout=300,
    )
    _run("cache_rebuild", [str(VENV_PYTHON), "scripts/cache_signals.py"], timeout=300)
    # Backtest refresh: keep /backtest page in sync with current data
    # (per-signal metrics feed the hypothesis-wise backtest table)
    _run(
        "cluster_backtest",
        [
            str(VENV_PYTHON),
            "scripts/cluster_backtest.py",
            "--signals",
            "dz_hi_up,dz_hi_dn,dz_lo_up,spike_70,streak3",
        ],
        timeout=900,
    )
    # Surveillance data: ASM/GSM from NSE (uses SeleniumBase anti-detection)
    _run(
        "surveillance_scrape",
        [str(VENV_PYTHON), "scripts/scrape_nse_surveillance.py", "--save-json", "--ingest-pg"],
        timeout=180,
    )
    _run(
        "surveillance_analysis",
        [str(VENV_PYTHON), "scripts/analyze_surveillance.py", "--top", "15"],
        timeout=600,
    )
    _run(
        "surveillance_paper_trade",
        [str(VENV_PYTHON), "scripts/surveillance_paper_trade.py", "--top", "7"],
        timeout=120,
    )
    # Professional quant layer: fundamentals, institutional, sectors, risk
    _run(
        "ingest_fundamentals",
        [str(VENV_PYTHON), "scripts/ingest_fundamentals.py", "--recent"],
        timeout=600,
    )
    _run(
        "ingest_institutional",
        [str(VENV_PYTHON), "scripts/ingest_institutional.py", "--daily"],
        timeout=300,
    )
    _run("ingest_sectors", [str(VENV_PYTHON), "scripts/ingest_sectors.py"], timeout=600)
    _run("compute_risk", [str(VENV_PYTHON), "scripts/compute_risk.py"], timeout=300)
    _run("sugg_settle", [str(VENV_PYTHON), "scripts/suggestion_manager.py", "settle"], timeout=60)
    _run("sugg_record", [str(VENV_PYTHON), "scripts/suggestion_manager.py", "record"], timeout=120)
    _run("watchlist_update", [str(VENV_PYTHON), "scripts/watchlist_signal_update.py"], timeout=60)
    # Hypothesis framework: generate signals + settle trades
    # Circuit breaker data: NSE price bands + Upstox snapshot
    _run(
        "circuit_ingest",
        [str(VENV_PYTHON), "scripts/ingest_circuit_limits.py", "--date", today],
        timeout=300,
    )
    _run("circuit_snapshot", [str(VENV_PYTHON), "scripts/snapshot_circuit_limits.py"], timeout=600)
    _run(
        "circuit_live_detect",
        [str(VENV_PYTHON), "scripts/detect_live_circuits.py", "--top", "7"],
        timeout=300,
    )
    _run(
        "circuit_patterns",
        [str(VENV_PYTHON), "scripts/analyze_circuit_patterns.py", "--days", "180"],
        timeout=600,
    )
    # Hypothesis framework: generate signals + settle trades
    # Use yesterday's date: at 18:33 on day T, bulk_ingest has written day T's data,
    # so T-1 cluster_entry (delivery) and continuation (circuit) are confirmed.
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _run(
        "hypothesis_signals",
        [str(VENV_PYTHON), "scripts/hypothesis_signals.py", "--date", yesterday],
        timeout=300,
    )
    _run("hypothesis_settle", [str(VENV_PYTHON), "scripts/hypothesis_settle.py"], timeout=300)
    # Safety net: cap open paper positions to top 7 per hypothesis
    _run(
        "cap_positions",
        [str(VENV_PYTHON), "scripts/cap_hypothesis_positions.py", "--top", "7"],
        timeout=300,
    )
    _run("status_report", [str(VENV_PYTHON), "scripts/status_report.py"], timeout=30)
    log.info("═══ EVENING CYCLE COMPLETE ═══")


def night_stop() -> None:
    """21:00 IST — Stop heavy jobs, keep web alive for research."""
    log.info("═══ NIGHT STOP (21:00 IST) ═══")
    stop_heavy()
    if _pgrep("nse-bse-mcp"):
        log.info("Stopping MCP...")
        subprocess.run(["pkill", "-f", "nse-bse-mcp"], capture_output=True, timeout=5)
        time.sleep(2)
    log.info("Heavy jobs and MCP stopped. Web stays alive for research.")


def health_check() -> None:
    """Quick health check — restart dead services."""
    now = _now_ist()
    h = now.hour
    is_market = _weekday() and 8 <= h < 16
    is_evening = _weekday() and 18 <= h < 21

    # Web always running — restart anytime it's dead
    if not _port_open(8080):
        log.warning("Health check: Web dead, restarting...")
        start_web()

    # MCP only during market/evening hours
    if (is_market or is_evening) and not _port_open(3000):
        log.warning("Health check: MCP dead, restarting...")
        start_mcp()


# ── Scheduler loop ─────────────────────────────────────────────────────────


def _handle_signal(sig, frame):
    global _running
    log.info(f"Received signal {sig}, shutting down...")
    _running = False


def run_scheduler() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("Platform scheduler started")
    log.info(f"ROOT={ROOT} VENV_PYTHON={VENV_PYTHON}")

    # Track what we've done today
    done_morning = False
    done_market_close = False
    done_evening = False
    done_night = False
    last_refresh = 0.0
    last_health = 0.0

    while _running:
        now = _now_ist()
        h, m = now.hour, now.minute
        minute = h * 60 + m

        # Reset daily flags at midnight
        if h == 0 and m == 0:
            done_morning = False
            done_market_close = False
            done_evening = False
            done_night = False

        # 08:00 — Morning start
        if h == 8 and m == 0 and not done_morning:
            morning_start()
            done_morning = True

        # 08:30–15:30 — Market hours refresh every 30 min
        if (
            _weekday()
            and 8 <= h < 16
            and minute >= 8 * 60 + 30
            and (minute - last_refresh >= 30 or last_refresh == 0)
        ):
            market_hours_refresh()
            last_refresh = minute

        # 16:00 — Market close
        if h == 16 and m == 0 and not done_market_close:
            market_close()
            done_market_close = True

        # 18:00 — Evening cycle
        if h == 18 and m == 0 and not done_evening:
            evening_cycle()
            done_evening = True

        # 18:00–21:00 — Evening Redis warm every 30 min
        if _weekday() and 18 <= h < 21 and (minute - last_refresh >= 30 or last_refresh == 0):
            if not done_evening:  # skip if evening cycle just ran
                market_hours_refresh()
            last_refresh = minute

        # 21:00 — Night stop
        if h == 21 and m == 0 and not done_night:
            night_stop()
            done_night = True

        # Health check every 30 min
        if minute - last_health >= 30:
            health_check()
            last_health = minute

        time.sleep(30)  # Check every 30 seconds


def main() -> int:
    parser = argparse.ArgumentParser(description="Platform scheduler daemon")
    parser.add_argument("--daemon", action="store_true", help="Fork to background (nohup)")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.daemon:
        pid = os.fork()
        if pid > 0:
            print(f"Scheduler daemon started (PID {pid})")
            print(f"Logs: {LOG_DIR}/scheduler.log")
            return 0
        # Child: detach
        os.setsid()
        sys.stdin.close()
        sys.stdout = open(LOG_DIR / "scheduler.log", "a")
        sys.stderr = sys.stdout

    run_scheduler()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
