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
main.py — NSE Bot Entry Point for Railway (nse-bot service)
============================================================
Fetches both telegram_last_scan.json AND scan_history.json
from GitHub on startup so all views work correctly.
"""

import base64
import json
import os
import sys
import types
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    print("[ERROR] Missing dependency: requests")
    print("[HINT] Install dependencies: pip install -r requirements.txt")
    sys.exit(1)

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "JayeshSRathod/nse-scanner").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip()

print(f"[MAIN] TELEGRAM_TOKEN   = {'SET (' + TOKEN[:15] + '...)' if TOKEN else 'NOT SET'}")
print(f"[MAIN] TELEGRAM_CHAT_ID = {CHAT_ID or 'NOT SET'}")

if not TOKEN:
    print("[ERROR] TELEGRAM_TOKEN not set")
    sys.exit(1)
if not CHAT_ID:
    if ADMIN_CHAT_ID:
        CHAT_ID = ADMIN_CHAT_ID
        print("[MAIN] TELEGRAM_CHAT_ID missing, using ADMIN_CHAT_ID fallback")
    else:
        print("[MAIN] TELEGRAM_CHAT_ID not set (continuing in polling-only mode)")

# ── Build config ──────────────────────────────────────────────
config = types.ModuleType("config")
config.TELEGRAM_TOKEN = TOKEN
config.TELEGRAM_CHATID = CHAT_ID
config.OUTPUT_DIR = "output"
config.LOG_DIR = "logs"
config.DB_PATH = "nse_scanner.db"
config.NSE_DATA_DIR = "nse_data"
config.DATA_DIR = "nse_data"
config.MIN_PRICE = 50
config.MIN_VOLUME = 50000
config.MIN_DELIVERY = 35
config.MAX_ANNVOL = 1.5
config.MAX_PE = 80
config.TOP_N_STOCKS = 25
config.WEIGHT_1M = 0.20
config.WEIGHT_2M = 0.30
config.WEIGHT_3M = 0.50
config.DAYS_1M = 22
config.DAYS_2M = 44
config.DAYS_3M = 66
config.BONUS_52W_HIGH = 0.05
config.BONUS_TOP25 = 0.03
sys.modules["config"] = config
print("[MAIN] Config module built")

for folder in ["logs", "output", "nse_data"]:
    Path(folder).mkdir(exist_ok=True)


# ── GitHub file fetcher ───────────────────────────────────────


def fetch_file_from_github(filename: str) -> bool:
    """Download a file from GitHub repo."""
    if not GITHUB_TOKEN:
        print(f"[GITHUB] No token — cannot fetch {filename}")
        return False

    print(f"[GITHUB] Fetching {filename} from {GITHUB_REPO}...")
    try:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}?ref={GITHUB_BRANCH}"
        r = requests.get(url, headers=headers, timeout=15)

        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"]).decode("utf-8")
            Path(filename).write_text(content, encoding="utf-8")
            parsed = json.loads(content)

            # Print summary based on file type
            if filename == "telegram_last_scan.json":
                print(f"[GITHUB] ✅ {filename}: {parsed.get('total_stocks')} stocks (date: {parsed.get('scan_date')})")
            elif filename == "scan_history.json":
                print(f"[GITHUB] ✅ {filename}: {parsed.get('days_stored', 0)} days stored")
            return True

        if r.status_code == 404:
            print(f"[GITHUB] {filename} not on GitHub yet")
            return False
        print(f"[GITHUB] ❌ {r.status_code}: {r.text[:100]}")
        return False

    except Exception as e:
        print(f"[GITHUB] Error fetching {filename}: {e}")
        return False


# ── Fetch telegram_last_scan.json ─────────────────────────────
RESULTS_FILE = Path("telegram_last_scan.json")

if RESULTS_FILE.exists():
    try:
        existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        stocks = existing.get("total_stocks", 0)
        scan_date = existing.get("scan_date", "?")
        print(f"[MAIN] Local scan data: {stocks} stocks (date: {scan_date})")

        # Always fetch latest (pipeline updates daily)
        print("[MAIN] Syncing latest scan from GitHub...")
        fetch_file_from_github("telegram_last_scan.json")

    except Exception:
        fetch_file_from_github("telegram_last_scan.json")
else:
    fetched = fetch_file_from_github("telegram_last_scan.json")
    if not fetched:
        print("[MAIN] Writing sample data (5 stocks)")
        sample = {
            "scan_date": str(date.today()),
            "total_stocks": 5,
            "page_size": 5,
            "stocks": [
                {
                    "rank": 1,
                    "symbol": "RELIANCE",
                    "score": 8,
                    "return_1m_pct": 5.2,
                    "return_2m_pct": 9.1,
                    "return_3m_pct": 18.4,
                    "close": 2450,
                    "volume": 8500000,
                    "delivery_pct": 52.3,
                    "sl": 2278,
                    "target1": 2622,
                    "target2": 2794,
                },
                {
                    "rank": 2,
                    "symbol": "HDFCBANK",
                    "score": 7,
                    "return_1m_pct": 4.1,
                    "return_2m_pct": 7.8,
                    "return_3m_pct": 14.2,
                    "close": 1680,
                    "volume": 12000000,
                    "delivery_pct": 61.5,
                    "sl": 1562,
                    "target1": 1798,
                    "target2": 1916,
                },
                {
                    "rank": 3,
                    "symbol": "INFY",
                    "score": 7,
                    "return_1m_pct": 3.8,
                    "return_2m_pct": 6.2,
                    "return_3m_pct": 11.5,
                    "close": 1520,
                    "volume": 6200000,
                    "delivery_pct": 55.8,
                    "sl": 1414,
                    "target1": 1626,
                    "target2": 1732,
                },
                {
                    "rank": 4,
                    "symbol": "TCS",
                    "score": 6,
                    "return_1m_pct": 2.9,
                    "return_2m_pct": 5.1,
                    "return_3m_pct": 9.8,
                    "close": 3820,
                    "volume": 3100000,
                    "delivery_pct": 67.2,
                    "sl": 3553,
                    "target1": 4087,
                    "target2": 4354,
                },
                {
                    "rank": 5,
                    "symbol": "WIPRO",
                    "score": 6,
                    "return_1m_pct": 2.1,
                    "return_2m_pct": 4.3,
                    "return_3m_pct": 8.2,
                    "close": 480,
                    "volume": 9800000,
                    "delivery_pct": 48.6,
                    "sl": 446,
                    "target1": 514,
                    "target2": 548,
                },
            ],
        }
        RESULTS_FILE.write_text(json.dumps(sample, indent=2), encoding="utf-8")
        print("[MAIN] Sample data written — real data arrives at 6:00 AM IST")

# ── Fetch scan_history.json ───────────────────────────────────
HISTORY_FILE = Path("scan_history.json")

if not HISTORY_FILE.exists():
    fetched = fetch_file_from_github("scan_history.json")
    if not fetched:
        print("[MAIN] No history yet — New/Exit/Strong views will show building message")
else:
    try:
        h = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        print(f"[MAIN] Local history: {h.get('days_stored', 0)} days")
        # Always refresh history from GitHub (pipeline updates it daily)
        fetch_file_from_github("scan_history.json")
    except Exception:
        fetch_file_from_github("scan_history.json")

# ── Fetch news_latest.json for the News Tab ───────────────────
fetch_file_from_github("output/news_latest.json")

# ── Start bot ─────────────────────────────────────────────────
print("\n[MAIN] Starting @nsescanner_live_bot (Phase 2)...")
print("[MAIN] Views: Today / New / Exit / Strong\n")

try:
    import nse_telegram_polling as bot

    bot.main()
except KeyboardInterrupt:
    print("\n[MAIN] Stopped")
except Exception as e:
    print(f"\n[MAIN] Bot crashed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
