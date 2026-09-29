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
Deployment verification — fast checks first, pipeline optional.

Usage:
  python verify_deployment.py                     # checks only (~5s)
  python verify_deployment.py --fast              # checks + pipeline (skip prices)
  python verify_deployment.py --full              # checks + full pipeline
  python verify_deployment.py --sweep             # add 2y/3y/4y walk-forward
  python verify_deployment.py --fast --sweep      # most common combo
"""
import datetime as dt
import os
import subprocess
import sys
import time

import db


def _check(ok, label, detail=""):
    mark = "✓" if ok else "✗"
    color = "\033[92m" if ok else "\033[91m"
    reset = "\033[0m"
    line = f"  {color}{mark}{reset}  {label:<40}"
    if detail:
        line += f"  {detail}"
    print(line, flush=True)
    return ok


def _strip_prefix(val):
    """Strip 'tv:' / 'csv:' / 'calc:' prefix from uploaded_at values."""
    s = str(val)
    if ":" in s:
        # keep the right side if it looks ISO-ish
        left, right = s.split(":", 1)
        if left in ("tv", "csv", "calc"):
            return right
    return s


def _table_fresh(conn, table, col="date", max_days=5):
    try:
        r = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
        latest = r[0] if r else None
        if not latest:
            return False, "empty"
        cleaned = _strip_prefix(latest)
        try:
            d = dt.date.fromisoformat(str(cleaned)[:10])
        except Exception:
            return False, f"unparseable date: {latest}"
        age = (dt.date.today() - d).days
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return age <= max_days, f"latest {str(cleaned)[:10]} ({age}d), {n} rows"
    except Exception as e:
        return False, f"err: {e}"


def run_checks():
    print("=" * 70)
    print("DEPLOYMENT VERIFICATION")
    print(f"Time: {dt.datetime.now().isoformat(timespec='seconds')}")
    print("=" * 70)
    print(flush=True)

    conn = db.get_conn()
    fails = 0

    print("DATA TABLES")
    for table, col, days in [
        ("prices_daily", "date", 5),
        ("technicals_daily", "date", 5),
        ("universe_broad", "updated_at", 30),
        ("fundamentals", "uploaded_at", 30),
        ("swing_signals", "signal_date", 14),
        ("trend_candidates", "date", 5),
        ("value_radar", "date", 30),
        ("positional_picks", "date", 30),
        ("pwin_daily", "date", 14),
    ]:
        ok, detail = _table_fresh(conn, table, col, days)
        if not ok:
            fails += 1
        _check(ok, table, detail)

    try:
        n = conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0]
        ok = n > 0
        _check(ok, "strategy_runs", f"{n} runs logged")
        if not ok:
            fails += 1
    except Exception as e:
        _check(False, "strategy_runs", f"err: {e}")
        fails += 1

    conn.close()
    print(flush=True)

    print("MODEL FILES")
    ml_ok = os.path.exists("data/ml_models.pkl")
    _check(ml_ok, "data/ml_models.pkl", "present" if ml_ok else "missing — run: python ml_train.py")
    if not ml_ok:
        fails += 1
    meta_ok = os.path.exists("data/meta_model.pkl")
    _check(meta_ok, "data/meta_model.pkl", "present" if meta_ok else "missing — run: python meta_model.py train")
    if not meta_ok:
        fails += 1
    gcp_ok = os.path.exists("data/gcp_key.json")
    _check(True, "data/gcp_key.json", "present" if gcp_ok else "absent (sheets sync will skip — OK)")
    print(flush=True)

    print("TODAY'S ACTIVITY")
    conn = db.get_conn()
    today = dt.date.today().isoformat()
    try:
        n = conn.execute("SELECT COUNT(*) FROM swing_signals WHERE signal_date=?", (today,)).fetchone()[0]
        _check(True, "swing signals today", f"{n} signals")
    except Exception as e:
        _check(False, "swing signals today", str(e))
    try:
        n = conn.execute("SELECT COUNT(*) FROM trend_candidates WHERE date=?", (today,)).fetchone()[0]
        _check(True, "trend candidates today", f"{n} stocks")
    except Exception as e:
        _check(False, "trend candidates today", str(e))
    conn.close()
    print(flush=True)

    print("CONFIG SANITY")
    try:
        from strategy_config import BACKTEST, SETUP, SIZING

        _check(
            True,
            "strategy_config loads",
            f"TARGET_R={BACKTEST['TARGET_R']}, "
            f"impulse={SETUP['IMPULSE_MIN_PCT']}-"
            f"{SETUP['IMPULSE_MAX_PCT']}, "
            f"max_alloc={SIZING['MAX_ALLOC']}",
        )
    except Exception as e:
        _check(False, "strategy_config loads", str(e))
        fails += 1
    print(flush=True)

    print("ALERTS")
    try:
        from alerts import _creds

        token, chat = _creds()
        ok = bool(token and chat)
        _check(ok, "Telegram credentials", "secret file or env" if ok else "MISSING")
        if not ok:
            fails += 1
    except Exception as e:
        _check(False, "Telegram credentials", str(e))
        fails += 1
    print(flush=True)

    print("API")
    try:
        import requests

        r = requests.get("http://127.0.0.1:8000/api/health", auth=("ankit", "ankitc21"), timeout=5)
        if r.status_code == 200:
            d = r.json()
            _check(True, "API /api/health", f"{d.get('prices_rows', 0):,} price rows")
        else:
            _check(False, "API /api/health", f"status {r.status_code}")
            fails += 1
    except Exception as e:
        _check(False, "API /api/health", str(e))
        fails += 1

    print(flush=True)
    print("=" * 70)
    if fails == 0:
        print("\033[92m✓ ALL CHECKS PASSED\033[0m")
    else:
        print(f"\033[91m{fails} checks failed\033[0m")
    print("=" * 70)
    print(flush=True)
    return fails


def run_pipeline(skip_prices=False):
    mode = "FAST (skipping prices ingest)" if skip_prices else "FULL"
    print("=" * 70)
    print(f"RUNNING DAILY PIPELINE — {mode}")
    print("=" * 70, flush=True)
    t0 = time.time()

    steps = ["prices", "technicals", "scan", "ml", "pwin", "toppicks", "events", "swing", "telegram", "sheets"]

    for name in steps:
        if name == "prices" and skip_prices:
            print(f"\n[{name}] SKIPPED (fast mode)", flush=True)
            continue
        t = time.time()
        print(f"\n[{name}] starting...", flush=True)
        try:
            if name == "prices":
                import ingest_prices

                ingest_prices.run(show_every=100)
            elif name == "technicals":
                import technicals

                technicals.compute_all()
            elif name == "scan":
                import scan

                scan.run()
            elif name == "ml":
                import ml_predict

                ml_predict.predict_all()
            elif name == "pwin":
                import pwin_cache

                pwin_cache.refresh_all()
            elif name == "toppicks":
                import top_picks

                top_picks.compute(force=True)
            elif name == "events":
                import events

                events.detect()
            elif name == "swing":
                import swing_live

                swing_live.update_outcomes()
                swing_live.scan()
            elif name == "telegram":
                from alerts import report

                report()
            elif name == "sheets":
                import sheets_sync

                sheets_sync.sync()
            dt_sec = time.time() - t
            print(f"[{name}] OK ({dt_sec:.1f}s)", flush=True)
        except Exception as e:
            print(f"[{name}] FAILED: {e}", flush=True)

    print()
    print(f"Pipeline complete in {time.time() - t0:.1f}s")
    print("=" * 70, flush=True)


def run_sweep():
    print("=" * 70)
    print("WALK-FORWARD SWEEP — 2y / 3y / 4y")
    print("=" * 70, flush=True)
    for years in [2, 3, 4]:
        print(f"\n--- {years}-year window ---", flush=True)
        t0 = time.time()
        subprocess.run(["python", "fast_wf.py", "--years", str(years)], check=False)
        print(f"({time.time() - t0:.1f}s)", flush=True)
    print(flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    fails = run_checks()
    if "--full" in args:
        run_pipeline(skip_prices=False)
    elif "--fast" in args:
        run_pipeline(skip_prices=True)
    if "--sweep" in args:
        run_sweep()
    sys.exit(0 if fails == 0 else 1)
