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
NSE Factor Engine — Master Pipeline Runner

Stages 1-6 unchanged. Market movement fetch now calls data/fetch_index_data.py
(single source of truth for all index OHLCV) instead of market_movement/fetch_index_data.py.
"""
import glob
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path("/home/ec2-user/nse-factor-engine")
FAILED_SYMBOL_HALT_THRESHOLD = 5

LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
RUN_LOG_PATH = LOG_DIR / f"master_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log(msg):
    print(msg)
    with open(RUN_LOG_PATH, "a") as f:
        f.write(msg + "\n")


def run_stage(label, script_path, extra_env=None):
    log("\n" + "=" * 70)
    log(f"STARTING {label}")
    log(f"Script: {script_path}")
    log(f"Time  : {datetime.now().isoformat()}")
    log("=" * 70)

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    process = subprocess.Popen(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in process.stdout:
        log(line.rstrip("\n"))

    process.wait()
    returncode = process.returncode

    if returncode != 0:
        log(f"\n!!! {label} FAILED with exit code {returncode} !!!")
        log(f"Halting pipeline. See {RUN_LOG_PATH} for full output.")
        sys.exit(1)

    log(f"\n{label} completed successfully (exit code 0).")
    return returncode


def run_stage_optional(label, script_path, extra_env=None):
    log("\n" + "=" * 70)
    log(f"STARTING {label}  [OPTIONAL — will not halt pipeline on failure]")
    log(f"Script: {script_path}")
    log(f"Time  : {datetime.now().isoformat()}")
    log("=" * 70)

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    process = subprocess.Popen(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in process.stdout:
        log(line.rstrip("\n"))

    process.wait()
    returncode = process.returncode

    if returncode != 0:
        log(f"\n!!! WARNING: {label} FAILED with exit code {returncode} !!!")
        log("!!! Pipeline continues — portfolio recommendations are unaffected.")
        log(f"!!! To run manually: cd {BASE} && python3 {script_path}")
        log(f"!!! Full output above. See {RUN_LOG_PATH} for details.")
    else:
        log(f"\n{label} completed successfully (exit code 0).")

    return returncode


def check_stage1_failures():
    import zoneinfo

    ist_today = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).date()
    failed_path = BASE / "data" / f"failed_symbols_{ist_today.strftime('%Y%m%d')}.csv"
    if not failed_path.exists():
        return 0, None
    import pandas as pd

    failed_df = pd.read_csv(failed_path)
    return len(failed_df), failed_path


def main():
    log("#" * 70)
    log("NSE FACTOR ENGINE — MASTER PIPELINE RUN")
    log(f"Started: {datetime.now().isoformat()}")
    log(f"Log file: {RUN_LOG_PATH}")
    log("#" * 70)

    # If STAGE6_MODE already set in environment (e.g. called from Telegram bot),
    # skip the interactive prompt entirely.
    if os.environ.get("STAGE6_MODE") in ("rebalance", "monitor", "mid_month"):
        log(f"Pipeline mode: {os.environ['STAGE6_MODE'].upper()} (from environment)")
    else:
        print("\n" + "=" * 70)
        print("NSE FACTOR ENGINE — PIPELINE MODE SELECTION")
        print("=" * 70)
        print("  1. REBALANCE  — full pipeline (stages 1-6), rebalances if >= 30 days")
        print("  2. MONITOR    — full pipeline (stages 1-6), Stage 6 read-only")
        print("  3. MID_MONTH  — full pipeline + day-15 RSI exit + replacement")
        print("                  (same as monitor but updates portfolio_state)")
        print("=" * 70)
        while True:
            choice = input("\nEnter mode [1=REBALANCE / 2=MONITOR / 3=MID_MONTH]: ").strip().lower()
            if choice in ("1", "rebalance", "r"):
                os.environ["STAGE6_MODE"] = "rebalance"
                log("Pipeline mode: REBALANCE")
                break
            if choice in ("2", "monitor", "m"):
                os.environ["STAGE6_MODE"] = "monitor"
                log("Pipeline mode: MONITOR")
                break
            if choice in ("3", "mid_month", "mid", "mm"):
                os.environ["STAGE6_MODE"] = "mid_month"
                log("Pipeline mode: MID_MONTH")
                break
            print("  Invalid — enter 1, 2, or 3 (or r/m/mm)")

    run_stage(
        "STAGE 1 — Universe & Liquidity",
        BASE / "universe" / "run_universe.py",
        extra_env={"TZ": "Asia/Kolkata"},
    )

    n_failed, failed_path = check_stage1_failures()
    if n_failed > 0:
        log(f"\nStage 1 finished with {n_failed} symbol(s) still failing.")
        log(f"Failed symbols file: {failed_path}")
        if n_failed >= FAILED_SYMBOL_HALT_THRESHOLD:
            log(
                f"\n!!! HALTING: {n_failed} failures >= threshold "
                f"({FAILED_SYMBOL_HALT_THRESHOLD}). Pipeline will NOT "
                f"proceed on a meaningfully incomplete universe. !!!"
            )
            sys.exit(1)
        else:
            log(
                f"\n{n_failed} failures < threshold "
                f"({FAILED_SYMBOL_HALT_THRESHOLD}) — proceeding, but this is a WARNING."
            )
    else:
        log("\nStage 1: 0 failed symbols. Clean universe run.")

    run_stage(
        "STAGE 2 — Momentum Core Signals",
        BASE / "signals" / "stage2" / "stage2_step5_assemble.py",
    )

    run_stage(
        "STAGE 3 — Momentum Quality Signals",
        BASE / "signals" / "stage3" / "stage3_assemble.py",
    )

    run_stage(
        "STAGE 4 — Entry Quality Filters",
        BASE / "signals" / "stage4" / "stage4_assemble.py",
    )

    run_stage(
        "STAGE 5 — Ranking & Selection",
        BASE / "signals" / "stage5" / "stage5_assemble.py",
    )

    run_stage(
        "STAGE 6 — Portfolio Selection (RSI Overlay)",
        BASE / "signals" / "stage6" / "stage6_assemble_rsi_overlay.py",
    )

    # Single unified index fetch — writes to data/index_prices.parquet
    run_stage(
        "INDEX FETCH — data/fetch_index_data.py (single source of truth)",
        BASE / "data" / "fetch_index_data.py",
        extra_env={"TZ": "Asia/Kolkata"},
    )

    run_stage(
        "MARKET MOVEMENT — Compute Breadth Metrics",
        BASE / "market_movement" / "compute_breadth_metrics.py",
    )

    run_stage(
        "MARKET MOVEMENT — Compute Metrics",
        BASE / "market_movement" / "compute_market_metrics.py",
    )

    run_stage_optional(
        "MARKET MOVEMENT — Generate PDF Report",
        BASE / "market_movement" / "generate_market_report.py",
    )

    final_files = sorted(glob.glob(str(BASE / "signals" / "final" / "momentum_signals_final_*.parquet")))
    final_files = [f for f in final_files if "backup" not in f]

    log("\n" + "#" * 70)
    log("PIPELINE COMPLETE")
    log(f"Finished: {datetime.now().isoformat()}")
    log(f"Final signals file(s): {final_files}")
    log(f"Full run log: {RUN_LOG_PATH}")
    log("#" * 70)


if __name__ == "__main__":
    main()
