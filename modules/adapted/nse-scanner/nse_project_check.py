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
nse_project_check.py — Complete Project Health Check
=====================================================
Run anytime to verify your entire NSE scanner project
is correctly set up and all components work together.

Usage:
    python nse_project_check.py

Checks:
    1.  All required files exist
    2.  Config + .env values loaded correctly
    3.  All Python imports work
    4.  SQLite database accessible + has data
    5.  NSE data folder (nse_data/) has files
    6.  Telegram token + chat reachable
    7.  telegram_last_scan.json valid + sorted
    8.  Output/log folders writable
    9.  Bot message formatting works
    10. Git / GitHub status
"""

import importlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).parent

# ── Results store ─────────────────────────────────────────────
_results = []


def _check(category, label, passed, detail="", fix=""):
    mark = "✅" if passed else "❌"
    _results.append((category, label, passed, detail, fix))
    print(f"  {mark}  {label}")
    if detail:
        print(f"       {detail}")
    if not passed and fix:
        print(f"       FIX: {fix}")


def _header(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


# ══════════════════════════════════════════════════════════════
# CHECK 1 — Required files
# ══════════════════════════════════════════════════════════════
_header("1. Required Files")

REQUIRED_FILES = [
    ("nse_daily_runner.py", "Master automation script"),
    ("nse_historical_downloader.py", "NSE data downloader"),
    ("nse_loader.py", "SQLite loader"),
    ("nse_scanner.py", "Stock scanner"),
    ("nse_output.py", "Excel + Telegram output"),
    ("nse_telegram_handler.py", "Bot handler + formatter"),
    ("nse_telegram_polling.py", "Polling bot"),
    ("nse_telegram_webhook.py", "Webhook bot (optional)"),
    ("setup_telegram_webhook.py", "Webhook setup helper"),
    ("config.py", "Project configuration"),
    (".env", "Secrets file (never commit this)"),
    ("nse_news_collector.py", "News collector"),
    ("auto_cleanup_nse_data.py", "Data cleanup"),
    ("nse_space_manager.py", "Space manager"),
    ("tg_diagnose.py", "Bot diagnostic"),
    (".gitignore", "Git ignore (protects .env)"),
    ("requirements.txt", "Python dependencies"),
]

for fname, desc in REQUIRED_FILES:
    path = _HERE / fname
    exists = path.exists()
    _check("Files", fname, exists, detail=desc, fix="Restore from Claude session or GitHub")


# ══════════════════════════════════════════════════════════════
# CHECK 2 — Config + .env values
# ══════════════════════════════════════════════════════════════
_header("2. Config + .env Values")

try:
    import config

    # Check .env loaded secrets
    env_checks = [
        ("TELEGRAM_TOKEN", "Telegram bot token"),
        ("TELEGRAM_CHATID", "Telegram chat ID"),
    ]
    for attr, desc in env_checks:
        val = getattr(config, attr, None)
        passed = bool(val)
        _check(
            "Config",
            attr,
            passed,
            detail=f"{desc} = {str(val)[:35] + '...' if val and len(str(val)) > 35 else val or 'NOT SET'}",
            fix=f"Add {attr.replace('CHATID', 'CHAT_ID')} to your .env file",
        )

    # Check path configs — support both NSE_DATA_DIR and DATA_DIR
    data_dir_val = getattr(config, "NSE_DATA_DIR", None) or getattr(config, "DATA_DIR", None)
    _check(
        "Config",
        "NSE_DATA_DIR / DATA_DIR",
        bool(data_dir_val),
        detail=f"data folder = {data_dir_val or 'NOT SET'}",
        fix="Add NSE_DATA_DIR = 'nse_data' to config.py",
    )

    for attr, desc in [
        ("OUTPUT_DIR", "Excel output folder"),
        ("LOG_DIR", "Log folder"),
        ("DB_PATH", "SQLite database path"),
    ]:
        val = getattr(config, attr, None)
        passed = bool(val)
        _check("Config", attr, passed, detail=f"{desc} = {val or 'NOT SET'}", fix=f"Add {attr} = 'value' to config.py")

    # Optional
    for attr in ["DHAN_CLIENT_ID", "DHAN_TOKEN"]:
        val = getattr(config, attr, None)
        mark = "✅" if val else "⚠️ "
        print(f"  {mark}  {attr} {'= set' if val else '= not set (optional — Dhan API)'}")

    # Thresholds sanity check
    thresh = [("MIN_PRICE", 50), ("MIN_VOLUME", 50000), ("TOP_N_STOCKS", 25), ("WEIGHT_3M", 0.5)]
    all_thresh = True
    for t, _default in thresh:
        if not hasattr(config, t):
            all_thresh = False
    _check(
        "Config",
        "Scanner thresholds present",
        all_thresh,
        detail="MIN_PRICE, MIN_VOLUME, TOP_N_STOCKS, WEIGHT_3M",
        fix="Check config.py — threshold values missing",
    )

except ImportError:
    _check(
        "Config",
        "config.py importable",
        False,
        fix="Ensure config.py exists and dotenv is installed: pip install python-dotenv",
    )


# ══════════════════════════════════════════════════════════════
# CHECK 3 — Python imports
# ══════════════════════════════════════════════════════════════
_header("3. Python Imports")

IMPORTS = [
    ("pandas", "pandas"),
    ("requests", "requests"),
    ("openpyxl", "openpyxl"),
    ("dotenv", "python-dotenv"),
    ("sqlite3", "sqlite3  (built-in)"),
    ("nse_telegram_handler", "nse_telegram_handler"),
    ("nse_output", "nse_output"),
    ("nse_scanner", "nse_scanner"),
    ("nse_loader", "nse_loader"),
]

_THIRD_PARTY = {"pandas", "requests", "openpyxl", "dotenv"}

for module, label in IMPORTS:
    try:
        importlib.import_module(module)
        _check("Imports", label, True)
    except ImportError as e:
        _check(
            "Imports",
            label,
            False,
            detail=str(e)[:80],
            fix=f"pip install {module}" if module in _THIRD_PARTY else "Restore the file from Claude or GitHub",
        )


# ══════════════════════════════════════════════════════════════
# CHECK 4 — SQLite database
# ══════════════════════════════════════════════════════════════
_header("4. SQLite Database")

try:
    import sqlite3

    import config as _cfg

    db_path = _HERE / getattr(_cfg, "DB_PATH", "nse_scanner.db")

    if db_path.exists():
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        tables = [t[0] for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        # Row count from main price table
        row_info = ""
        for tbl in ["daily_prices", "daily_data", "prices", "bhav"]:
            if tbl in tables:
                count = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                row_info = f"{count:,} rows in '{tbl}'"
                break

        # Date range
        date_info = ""
        for tbl in ["daily_prices", "daily_data"]:
            if tbl in tables:
                try:
                    row = cur.execute(f"SELECT MIN(date), MAX(date) FROM {tbl}").fetchone()
                    if row[0]:
                        date_info = f"  |  dates {row[0]} → {row[1]}"
                except Exception:
                    pass
                break
        con.close()

        size_mb = db_path.stat().st_size / 1_048_576
        _check(
            "Database",
            f"DB accessible: {db_path.name}",
            True,
            detail=f"{size_mb:.1f}MB  |  Tables: {tables}  |  {row_info}{date_info}",
        )
        _check("Database", "Has price data", bool(row_info), fix="Run: python nse_loader.py")
    else:
        _check(
            "Database",
            f"DB file found: {db_path.name}",
            False,
            fix="Run: python nse_loader.py  or  python nse_daily_runner.py --skip-download",
        )

except Exception as e:
    _check("Database", "Database check", False, detail=str(e))


# ══════════════════════════════════════════════════════════════
# CHECK 5 — NSE data folder
# ══════════════════════════════════════════════════════════════
_header("5. NSE Data Files  (nse_data/)")

try:
    import config as _cfg

    # Support both NSE_DATA_DIR and DATA_DIR
    data_dir_name = getattr(_cfg, "NSE_DATA_DIR", None) or getattr(_cfg, "DATA_DIR", "nse_data")
    data_dir = _HERE / data_dir_name

    if data_dir.exists():
        csv_files = list(data_dir.rglob("*.csv"))
        size_mb = sum(f.stat().st_size for f in csv_files) / 1_048_576

        _check(
            "Data",
            f"Folder exists: {data_dir_name}/",
            True,
            detail=f"{len(csv_files)} CSV files  |  {size_mb:.1f} MB total",
        )

        if csv_files:
            latest = max(csv_files, key=lambda f: f.stat().st_mtime)
            oldest = min(csv_files, key=lambda f: f.stat().st_mtime)
            age_days = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).days
            span = (
                datetime.fromtimestamp(latest.stat().st_mtime) - datetime.fromtimestamp(oldest.stat().st_mtime)
            ).days

            _check(
                "Data",
                "Latest CSV file recent (≤5 days)",
                age_days <= 5,
                detail=f"Latest: {latest.name}  ({age_days}d old)  |  Oldest: {oldest.name}  |  Span: {span} days",
                fix="Run: python nse_daily_runner.py",
            )

            # Warn if too many raw CSVs (already in SQLite — wasting space)
            if len(csv_files) > 30:
                print(f"  ⚠️   {len(csv_files)} raw CSVs on disk ({size_mb:.0f}MB) — data is already in SQLite.")
                print("       Run: python nse_space_manager.py --clean  to free space")
        else:
            _check("Data", "CSV files present", False, fix="Run: python nse_historical_downloader.py")
    else:
        _check(
            "Data",
            f"Folder exists: {data_dir_name}/",
            False,
            fix="Run: python nse_historical_downloader.py  (will create folder)",
        )

except Exception as e:
    _check("Data", "Data folder check", False, detail=str(e))


# ══════════════════════════════════════════════════════════════
# CHECK 6 — Telegram
# ══════════════════════════════════════════════════════════════
_header("6. Telegram")

try:
    import requests

    import config as _cfg

    token = getattr(_cfg, "TELEGRAM_TOKEN", "") or ""
    chat_id = str(getattr(_cfg, "TELEGRAM_CHATID", "") or "")
    base = f"https://api.telegram.org/bot{token}"

    # Token
    r = requests.get(f"{base}/getMe", timeout=5)
    data = r.json()
    if data.get("ok"):
        bot = data["result"]
        _check("Telegram", "Token valid", True, detail=f"@{bot['username']}  id={bot['id']}")
    else:
        _check(
            "Telegram",
            "Token valid",
            False,
            detail=data.get("description", ""),
            fix="Check TELEGRAM_TOKEN in .env file",
        )

    # Webhook
    wh_url = requests.get(f"{base}/getWebhookInfo", timeout=5).json().get("result", {}).get("url", "")
    if wh_url:
        _check(
            "Telegram",
            "No webhook blocking polling",
            False,
            detail=f"Webhook active: {wh_url}",
            fix="python setup_telegram_webhook.py --delete-webhook",
        )
    else:
        _check("Telegram", "No webhook blocking polling", True)

    _check(
        "Telegram",
        "Chat ID configured",
        bool(chat_id),
        detail=f"chat_id = {chat_id}" if chat_id else "NOT SET",
        fix="Add TELEGRAM_CHAT_ID to .env file",
    )

except Exception as e:
    _check("Telegram", "Telegram reachable", False, detail=str(e), fix="Check internet + TELEGRAM_TOKEN in .env")


# ══════════════════════════════════════════════════════════════
# CHECK 7 — Pagination JSON
# ══════════════════════════════════════════════════════════════
_header("7. Bot Pagination JSON  (telegram_last_scan.json)")

try:
    from nse_telegram_handler import RESULTS_FILE, load_scan_results

    if os.path.exists(RESULTS_FILE):
        res = load_scan_results()
        if res:
            stocks = res.get("stocks", [])
            scan_date = res.get("scan_date", "?")
            try:
                age_days = (date.today() - datetime.strptime(scan_date, "%Y-%m-%d").date()).days
            except Exception:
                age_days = 99

            _check("JSON", "File found + readable", True, detail=f"{RESULTS_FILE}")
            _check(
                "JSON",
                "Has stocks",
                len(stocks) > 0,
                detail=f"{len(stocks)} stocks  |  date={scan_date}  ({age_days}d old)",
                fix="Run: python nse_output.py --test",
            )
            _check(
                "JSON",
                "Data is recent (≤4 days)",
                age_days <= 4,
                detail=f"Scan date: {scan_date}",
                fix="Run: python nse_daily_runner.py",
            )

            if stocks:
                req = ["symbol", "score", "return_3m_pct", "close", "sl", "target1", "target2"]
                missing = [k for k in req if k not in stocks[0]]
                _check(
                    "JSON",
                    "All required fields present",
                    len(missing) == 0,
                    detail="Fields OK" if not missing else f"Missing: {missing}",
                    fix="Run: python nse_output.py --test",
                )

                # Sort order check
                if len(stocks) >= 2:
                    ok = stocks[0]["return_3m_pct"] >= stocks[1]["return_3m_pct"]
                    _check(
                        "JSON",
                        "Sorted by 3M return descending",
                        ok,
                        detail=f"#{1} {stocks[0]['symbol']} "
                        f"{stocks[0]['return_3m_pct']}%  |  "
                        f"#{2} {stocks[1]['symbol']} "
                        f"{stocks[1]['return_3m_pct']}%",
                        fix="Run: python nse_output.py --test  (re-saves sorted)",
                    )
        else:
            _check("JSON", "File readable", False, fix="Run: python nse_output.py --test")
    else:
        _check("JSON", "File found", False, detail=f"Expected: {RESULTS_FILE}", fix="Run: python nse_output.py --test")

except Exception as e:
    _check("JSON", "JSON check", False, detail=str(e))


# ══════════════════════════════════════════════════════════════
# CHECK 8 — Output folders writable
# ══════════════════════════════════════════════════════════════
_header("8. Output Folders")

try:
    import config as _cfg

    for attr, desc in [("OUTPUT_DIR", "Excel output"), ("LOG_DIR", "Logs")]:
        folder = _HERE / getattr(_cfg, attr, attr.lower())
        folder.mkdir(parents=True, exist_ok=True)
        test = folder / ".write_test"
        try:
            test.write_text("ok")
            test.unlink()
            _check("Folders", f"{desc} writable: {folder.name}/", True)
        except Exception as e:
            _check(
                "Folders", f"{desc} writable: {folder.name}/", False, detail=str(e), fix=f"Check permissions: {folder}"
            )

    # Latest Excel
    out_dir = _HERE / getattr(_cfg, "OUTPUT_DIR", "output")
    xlsx_files = sorted(out_dir.glob("NSE_Scanner_*.xlsx"), key=lambda f: f.stat().st_mtime, reverse=True)
    if xlsx_files:
        latest = xlsx_files[0]
        size = latest.stat().st_size / 1_048_576
        _check("Folders", "Excel report exists", True, detail=f"{latest.name}  ({size:.1f}MB)")
        if len(xlsx_files) > 1:
            print(f"  ⚠️   {len(xlsx_files)} Excel files found — run nse_space_manager.py --clean to keep only latest")
    else:
        print("  ⚠️   No Excel yet — will be created on next scan run")

except Exception as e:
    _check("Folders", "Folder check", False, detail=str(e))


# ══════════════════════════════════════════════════════════════
# CHECK 9 — Bot message formatting
# ══════════════════════════════════════════════════════════════
_header("9. Bot Message Formatting")

try:
    from nse_telegram_handler import format_help, format_stock_list, load_scan_results, sort_stocks

    res = load_scan_results()
    if res and res.get("stocks"):
        stocks = sort_stocks(res["stocks"], "3m")
        page_size = res["page_size"]
        msg = format_stock_list(stocks, 0, page_size, res["scan_date"])

        _check(
            "Format",
            "format_stock_list() runs without error",
            len(msg) > 50,
            detail=f"{len(msg)} chars  |  Page 1 stocks: {', '.join(s['symbol'] for s in stocks[:5])}",
        )
        _check("Format", "format_help() runs without error", len(format_help()) > 20)

        if len(stocks) >= 2:
            ok = stocks[0]["return_3m_pct"] >= stocks[1]["return_3m_pct"]
            _check(
                "Format",
                "Sort order correct (3M desc)",
                ok,
                detail=f"#{1} {stocks[0]['symbol']} "
                f"{stocks[0]['return_3m_pct']}%  "
                f"#{2} {stocks[1]['symbol']} "
                f"{stocks[1]['return_3m_pct']}%",
            )
    else:
        _check("Format", "Message formatting", False, fix="Run: python nse_output.py --test")

except Exception as e:
    _check("Format", "Message formatting", False, detail=str(e))


# ══════════════════════════════════════════════════════════════
# CHECK 10 — Git / GitHub
# ══════════════════════════════════════════════════════════════
_header("10. Git / GitHub")

try:
    import subprocess

    # Initialised?
    r = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=str(_HERE))
    if r.returncode == 0:
        _check("Git", "Git repo initialised", True)

        changed = [l for l in r.stdout.strip().splitlines() if not l.strip().startswith("??")]
        if changed:
            print(f"  ⚠️   {len(changed)} uncommitted file(s) — run: git add . && git commit -m 'update'")
        else:
            print("  ✅  Working tree clean — nothing to commit")

        # .env in gitignore?
        gi = _HERE / ".gitignore"
        if gi.exists():
            ignored = ".env" in gi.read_text()
            _check(
                "Git",
                ".env in .gitignore (secrets protected)",
                ignored,
                fix="Add '.env' line to .gitignore immediately!",
            )
        else:
            _check("Git", ".gitignore exists", False, fix="Create .gitignore and add .env to it")

        # Remote
        r2 = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True, cwd=str(_HERE))
        has_remote = "github.com" in r2.stdout
        _check(
            "Git",
            "GitHub remote configured",
            has_remote,
            fix="git remote add origin https://github.com/YOUR_USERNAME/nse-scanner.git",
        )
    else:
        _check("Git", "Git repo initialised", False, fix="Run: git init")

except FileNotFoundError:
    print("  ⚠️   Git not installed — skipping (optional)")


# ══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ══════════════════════════════════════════════════════════════
total = len(_results)
passed = sum(1 for r in _results if r[2])
failed = total - passed
all_ok = failed == 0

print(f"\n{'#' * 55}")
print("  PROJECT HEALTH SUMMARY")
print(f"{'#' * 55}")
print(f"  Passed : {passed}/{total}")
print(f"  Failed : {failed}/{total}")
print(f"{'─' * 55}")

if all_ok:
    print("""
  ✅  ALL CHECKS PASSED — project is healthy

  Daily routine:
    1. Task Scheduler fires nse_daily_runner.py at 6:45 PM
    2. You run : python nse_telegram_polling.py
    3. Telegram : /start → browse stocks with inline buttons
""")
else:
    print("\n  ❌  ITEMS TO FIX:\n")
    for cat, label, ok, _detail, fix in _results:
        if not ok:
            print(f"  [{cat}]  {label}")
            if fix:
                print(f"    → {fix}")

print("\n  Re-run anytime: python nse_project_check.py")
print(f"{'#' * 55}\n")
