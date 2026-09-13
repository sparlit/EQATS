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
nse_bot_admin.py — Bot Administration & Health Check (v2)
==========================================================
WHAT CHANGED FROM v1:
  1. format_guide_message() updated for new situation engine
     - Explains PRIME/WATCH/HOLD/BOOK/AVOID situations
     - Updated score explanation (forward-looking)
     - Added TV confirmation workflow

Everything else (user tracking, health check,
activity logging, admin commands) unchanged.
"""

import contextlib
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

try:
    import config
except ImportError:
    config = None

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent
USERS_FILE = _HERE / "bot_users.json"
ACTIVITY_FILE = _HERE / "logs" / "bot_activity.log"

# ── Admin chat IDs (add your Telegram user ID here) ───────────
ADMIN_IDS = set()
try:
    _admin_env = os.environ.get("ADMIN_CHAT_IDS", "")
    if _admin_env:
        for _id in _admin_env.split(","):
            with contextlib.suppress(Exception):
                ADMIN_IDS.add(int(_id.strip()))
except Exception:
    pass

ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0)) or (next(iter(ADMIN_IDS)) if ADMIN_IDS else 0)


# ═══════════════════════════════════════════════════════════════
# USER TRACKING (unchanged)
# ═══════════════════════════════════════════════════════════════


def _load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False, default=str)


def track_user(user):
    """Track a user interaction."""
    try:
        users = _load_users()
        uid = str(getattr(user, "id", user) if not isinstance(user, dict) else user.get("id", ""))
        if not uid:
            return

        today = date.today().isoformat()
        uname = getattr(user, "username", "") or (user.get("username", "") if isinstance(user, dict) else "")
        fname = getattr(user, "first_name", "") or (user.get("first_name", "") if isinstance(user, dict) else "")
        lname = getattr(user, "last_name", "") or (user.get("last_name", "") if isinstance(user, dict) else "")
        full = (fname + " " + lname).strip() or uname or uid

        if uid not in users:
            users[uid] = {
                "user_id": uid,
                "username": uname,
                "full_name": full,
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "total_visits": 0,
                "daily_visits": {},
                "is_blocked": False,
            }

        u = users[uid]
        u["last_seen"] = datetime.now().isoformat()
        u["total_visits"] = u.get("total_visits", 0) + 1
        u["username"] = uname or u.get("username", "")
        u["full_name"] = full or u.get("full_name", "")

        daily = u.setdefault("daily_visits", {})
        daily[today] = daily.get(today, 0) + 1

        _save_users(users)
    except Exception as e:
        log.debug(f"track_user error: {e}")


def is_admin(user_id):
    """Check if user_id is an admin."""
    return int(user_id) in ADMIN_IDS or int(user_id) == ADMIN_CHAT_ID


def is_blocked(user_id):
    """Check if user is blocked."""
    users = _load_users()
    user = users.get(str(user_id), {})
    return user.get("is_blocked", False)


def get_user_count():
    return len(_load_users())


# ═══════════════════════════════════════════════════════════════
# ACTIVITY LOGGING (unchanged)
# ═══════════════════════════════════════════════════════════════


def log_activity(user_id, action_type, action_data):
    """Log user activity to file."""
    try:
        ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = f"[{ts}] user={user_id} type={action_type} action={action_data}\n"
        with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
            f.write(row)
    except Exception as e:
        log.debug(f"log_activity error: {e}")


def get_activity_stats(days=1):
    """Get activity stats for last N days."""
    if not ACTIVITY_FILE.exists():
        return {"total_actions": 0, "unique_users": set(), "top_actions": []}
    try:
        cutoff = datetime.now() - timedelta(days=days)
        actions = {}
        users = set()
        total = 0

        with open(ACTIVITY_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    ts_str = line[1:20]
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    if ts < cutoff:
                        continue
                    total += 1
                    if "user=" in line:
                        uid = line.split("user=")[1].split(" ")[0]
                        users.add(uid)
                    if "action=" in line:
                        act = line.split("action=")[1].strip()
                        actions[act] = actions.get(act, 0) + 1
                except Exception:
                    continue

        top = sorted(actions.items(), key=lambda x: x[1], reverse=True)
        return {
            "total_actions": total,
            "unique_users": len(users),
            "top_actions": top[:10],
            "top_users": [],
        }
    except Exception as e:
        log.exception(f"get_activity_stats error: {e}")
        return {"total_actions": 0, "unique_users": 0, "top_actions": []}


def cleanup_old_activity(keep_days=30):
    """Remove activity log entries older than keep_days."""
    if not ACTIVITY_FILE.exists():
        return
    try:
        cutoff = datetime.now() - timedelta(days=keep_days)
        lines = []
        with open(ACTIVITY_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    ts = datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff:
                        lines.append(line)
                except Exception:
                    lines.append(line)
        with open(ACTIVITY_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        log.exception(f"cleanup_old_activity error: {e}")


# ═══════════════════════════════════════════════════════════════
# HEALTH REPORT (unchanged logic, updated situation awareness)
# ═══════════════════════════════════════════════════════════════


def generate_health_report():
    """Generate system health report."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "scan_status": "unknown",
        "scan_date": None,
        "stock_count": 0,
        "prime_count": 0,
        "db_ok": False,
        "db_size_mb": 0,
        "history_days": 0,
        "tracker_ok": False,
        "active_signals": 0,
        "user_count": 0,
        "activity": {},
    }

    # Scan results
    try:
        scan_file = Path("telegram_last_scan.json")
        if scan_file.exists():
            with open(scan_file, encoding="utf-8") as f:
                data = json.load(f)
            scan_date_str = data.get("scan_date", "")
            stocks = data.get("stocks", [])
            report["stock_count"] = len(stocks)
            report["scan_date"] = scan_date_str

            # Count prime situations
            prime = sum(1 for s in stocks if s.get("situation") == "prime")
            report["prime_count"] = prime

            if scan_date_str:
                try:
                    sd = datetime.strptime(scan_date_str, "%Y-%m-%d").date()
                    age = (date.today() - sd).days
                    report["scan_status"] = "fresh" if age <= 1 else "stale" if age <= 3 else "old"
                except Exception:
                    report["scan_status"] = "unknown"
    except Exception as e:
        log.exception(f"Health scan check: {e}")

    # Database
    try:
        db_path = Path(getattr(config, "DB_PATH", "nse_scanner.db"))
        if db_path.exists():
            report["db_ok"] = True
            report["db_size_mb"] = round(db_path.stat().st_size / 1_048_576, 1)
    except Exception:
        pass

    # History
    try:
        hist_file = Path("scan_history.json")
        if hist_file.exists():
            with open(hist_file, encoding="utf-8") as f:
                hist_data = json.load(f)
            report["history_days"] = hist_data.get("days_stored", 0)
    except Exception:
        pass

    # Tracker
    try:
        tracker_file = Path("signal_tracker.json")
        if tracker_file.exists():
            with open(tracker_file, encoding="utf-8") as f:
                tracker = json.load(f)
            report["tracker_ok"] = True
            report["active_signals"] = len(tracker.get("signals", {}))
    except Exception:
        pass

    # Users
    with contextlib.suppress(Exception):
        report["user_count"] = get_user_count()

    # Activity
    with contextlib.suppress(Exception):
        report["activity"] = get_activity_stats(days=1)

    return report


def format_health_report(report):
    """Format health report as HTML for Telegram."""
    ts = report.get("timestamp", "?")[:19]
    msg = "🏥 <b>NSE Bot Health Check</b>\n"
    msg += f"<i>{ts}</i>\n"
    msg += "━" * 30 + "\n\n"

    # Scan status
    scan_status = report.get("scan_status", "unknown")
    scan_icon = "✅" if scan_status == "fresh" else "⚠️" if scan_status == "stale" else "❌"
    prime_count = report.get("prime_count", 0)

    msg += "<b>📊 Scan Status</b>\n"
    msg += (
        f"  {scan_icon} Status: {scan_status.upper()}\n"
        f"  Date: {report.get('scan_date', 'unknown')}\n"
        f"  Stocks: {report.get('stock_count', 0)}\n"
        f"  🎯 Prime entries: {prime_count}\n\n"
    )

    # Database
    db_icon = "✅" if report.get("db_ok") else "❌"
    msg += "<b>🗄️ Database</b>\n"
    msg += (
        f"  {db_icon} Status: {'OK' if report.get('db_ok') else 'ERROR'}\n"
        f"  Size: {report.get('db_size_mb', 0):.1f} MB\n\n"
    )

    # History
    hist_days = report.get("history_days", 0)
    hist_icon = "✅" if hist_days >= 5 else "⚠️" if hist_days >= 2 else "❌"
    msg += "<b>📚 History</b>\n"
    msg += f"  {hist_icon} {hist_days} day(s) stored\n\n"

    # Tracker
    trk_icon = "✅" if report.get("tracker_ok") else "⚠️"
    msg += "<b>📈 Signal Tracker</b>\n"
    msg += f"  {trk_icon} Active signals: {report.get('active_signals', 0)}\n\n"

    # Users
    msg += "<b>👥 Users</b>\n"
    msg += f"  Total users: {report.get('user_count', 0)}\n\n"

    # Activity
    activity = report.get("activity", {})
    if activity:
        msg += "<b>📊 Activity (Today)</b>\n"
        msg += f"  Actions: {activity.get('total_actions', 0)}\n"
        msg += f"  Unique users: {activity.get('unique_users', 0)}\n"

        if activity.get("top_actions"):
            msg += "  🔝 Top actions:\n"
            for action, count in activity["top_actions"][:5]:
                msg += f"     <code>{action}</code>: {count}\n"

    msg += "\n" + "━" * 30 + "\n"
    msg += "<i>Next check: Tomorrow 11:30 PM</i>"
    return msg


# ═══════════════════════════════════════════════════════════════
# USER LIST FORMAT (unchanged)
# ═══════════════════════════════════════════════════════════════


def format_user_list():
    users = _load_users()
    if not users:
        return "👥 <b>Bot Users</b>\n\nNo users registered yet."

    msg = f"👥 <b>BOT USERS</b> ({len(users)} total)\n"
    msg += "━" * 30 + "\n\n"

    sorted_users = sorted(users.values(), key=lambda u: u.get("last_seen", ""), reverse=True)
    today_str = date.today().isoformat()

    for i, user in enumerate(sorted_users, 1):
        name = user.get("full_name", "Unknown")
        uname = user.get("username", "")
        uid = user.get("user_id", "?")
        visits = user.get("total_visits", 0)
        first = user.get("first_seen", "?")[:10]
        last = user.get("last_seen", "?")[:10]
        blocked = " 🚫" if user.get("is_blocked") else ""

        today_visits = user.get("daily_visits", {}).get(today_str, 0)
        active_badge = " 🟢" if today_visits > 0 else ""
        uname_str = f" @{uname}" if uname else ""

        msg += (
            f"<b>{i}.</b> {name}{uname_str}{active_badge}{blocked}\n"
            f"   ID: <code>{uid}</code> | "
            f"Visits: {visits} | "
            f"Since: {first} | "
            f"Last: {last}"
        )
        if today_visits > 0:
            msg += f" | Today: {today_visits}"
        msg += "\n\n"

    active = sum(1 for u in users.values() if u.get("daily_visits", {}).get(today_str, 0) > 0)
    msg += "━" * 30 + "\n"
    msg += f"🟢 Active today: {active} | 👥 Total: {len(users)}"
    return msg


def format_user_detail(user_id):
    users = _load_users()
    user = users.get(str(user_id))
    if not user:
        return f"User {user_id} not found."

    name = user.get("full_name", "Unknown")
    uname = user.get("username", "")
    visits = user.get("total_visits", 0)
    first = user.get("first_seen", "?")
    last = user.get("last_seen", "?")
    blocked = user.get("is_blocked", False)
    daily = user.get("daily_visits", {})

    msg = "👤 <b>User Detail</b>\n"
    msg += "━" * 30 + "\n\n"
    msg += f"Name: <b>{name}</b>\n"
    if uname:
        msg += f"Username: @{uname}\n"
    msg += f"ID: <code>{user_id}</code>\n"
    msg += f"Status: {'🚫 Blocked' if blocked else '✅ Active'}\n"
    msg += f"First seen: {first}\n"
    msg += f"Last seen: {last}\n"
    msg += f"Total visits: {visits}\n\n"

    if daily:
        msg += "<b>Daily Activity (last 7 days)</b>\n"
        for day, count in sorted(daily.items(), reverse=True)[:7]:
            bar = "█" * min(count, 20)
            msg += f"  {day}: {bar} {count}\n"

    return msg


# ═══════════════════════════════════════════════════════════════
# HEALTH SEND (unchanged)
# ═══════════════════════════════════════════════════════════════


def send_health_check():
    token = getattr(config, "TELEGRAM_TOKEN", "") if config else ""
    chat_id = ADMIN_CHAT_ID
    if not token or not chat_id:
        return False

    cleanup_old_activity(keep_days=30)
    report = generate_health_report()
    message = format_health_report(report)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return True
        # Fallback without HTML
        r2 = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message.replace("<b>", "")
                .replace("</b>", "")
                .replace("<i>", "")
                .replace("</i>", "")
                .replace("<code>", "")
                .replace("</code>", ""),
            },
            timeout=10,
        )
        return r2.status_code == 200
    except Exception as e:
        log.exception(f"Health check send error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# GUIDE MESSAGE — Updated for Situation Engine
# ═══════════════════════════════════════════════════════════════


def format_guide_message():
    """Format the scanner guide. Updated for v2 situation engine."""
    msg = "📖 <b>How to Read the NSE Scanner</b>\n"
    msg += "━" * 30 + "\n\n"

    msg += "<b>Your Daily Workflow</b>\n\n"
    msg += "1️⃣ <b>6 AM</b> — Bot sends scan automatically\n"
    msg += "2️⃣ <b>Tap /prime</b> — See stocks ready to enter\n"
    msg += "3️⃣ <b>Open TradingView</b> — Confirm each prime stock\n"
    msg += "4️⃣ <b>TV says ENTER</b> — Take the trade\n"
    msg += "5️⃣ <b>TV says WAIT</b> — Check again tomorrow\n\n"

    msg += "━" * 30 + "\n\n"

    msg += "<b>🎯 Situation Labels</b>\n\n"
    msg += "🎯 <b>Prime Entry</b>\n"
    msg += "  Best setup today. Fresh HMA cross, room to run,\n"
    msg += "  accumulation volume. Confirm on TradingView then enter.\n\n"

    msg += "💰 <b>Hold & Trail</b>\n"
    msg += "  Stock has been in top 25 for 5+ days.\n"
    msg += "  Already in a sustained move. Trail your stop loss up.\n\n"

    msg += "👀 <b>Watch Closely</b>\n"
    msg += "  Good setup but one signal missing.\n"
    msg += "  Could be ready in 1-3 days. Monitor daily.\n\n"

    msg += "⚠️ <b>Book Profits</b>\n"
    msg += "  Move is maturing. HMA cross was 30+ days ago\n"
    msg += "  or price is stretched 15%+ above HMA55.\n"
    msg += "  Consider booking 50-100% of profits.\n\n"

    msg += "🚫 <b>Avoid Now</b>\n"
    msg += "  Weak signal, distribution volume, or bearish.\n"
    msg += "  Skip completely. Better opportunities tomorrow.\n\n"

    msg += "━" * 30 + "\n\n"

    msg += "<b>📊 Score (0-10) — Forward Probability</b>\n"
    msg += "  Scores HOW LIKELY the stock gives profit NEXT 1-3M\n"
    msg += "  Not how well it performed in the LAST 3M\n\n"
    msg += "  Signal breakdown:\n"
    msg += "  HMA freshness (+2) — cross ≤10d vs 30d+\n"
    msg += "  Room to run (+2) — % above HMA55\n"
    msg += "  Volume quality (+2) — OBV + accumulation days\n"
    msg += "  RSI sweet spot (+1) — 40-65 zone\n"
    msg += "  MACD confirming (+1)\n"
    msg += "  Sector alignment (+1)\n"
    msg += "  Risk/Reward (+1) — SL ≤7%\n\n"

    msg += "  8-10 = HIGH CONVICTION (strongest)\n"
    msg += "  5-7  = WATCHLIST (good, wait for entry)\n"
    msg += "  0-4  = Not shown\n\n"

    msg += "━" * 30 + "\n\n"

    msg += "<b>📊 Trade Plan</b>\n"
    msg += "  Entry = Today's close price\n"
    msg += "  SL = 3% below HMA55 (trend line)\n"
    msg += "  T1 = Entry + 1× Risk (~1 month)\n"
    msg += "  T2 = Entry + 2× Risk (~3 months)\n"
    msg += "  RR = Always 1:2 minimum\n\n"

    msg += "<b>💰 When T1 hits:</b> Book 50%, move SL to entry\n"
    msg += "<b>💰 When T2 hits:</b> Book remaining 50%\n\n"

    msg += "━" * 30 + "\n\n"

    msg += "<b>📈 Probability Numbers</b>\n"
    msg += "  T1 probability = chance of reaching T1\n"
    msg += "  Based on score + freshness + room to run\n"
    msg += "  T1 >70% = high confidence setup\n"
    msg += "  Not guarantees — use as guidance only\n\n"

    msg += "━" * 30 + "\n"
    msg += "👇 <i>Tap the button below for the full PDF guide</i>\n\n"
    msg += (
        "📢 <i>For educational and informational purposes only. "
        "Not a SEBI registered investment advisor. "
        "Not investment advice. "
        "Always consult a qualified financial advisor before trading.</i>"
    )

    return msg


# ═══════════════════════════════════════════════════════════════
# BROADCAST — Send morning message to all registered users
# ═══════════════════════════════════════════════════════════════


def broadcast_to_all_users(token: str | None = None, skip_chat_id: int | None = None) -> dict:
    """
    Broadcast today's Option C scan message to all registered users.

    Called by admin after sending /broadcast and confirming YES.

    Args:
        token:        Telegram bot token
        skip_chat_id: Chat ID already sent to (admin's own chat)
                      These users won't get a duplicate message

    Returns:
        dict with sent, failed, blocked, skipped counts
    """
    if token is None:
        token = getattr(config, "TELEGRAM_TOKEN", None) if config else None
        if not token:
            token = os.environ.get("TELEGRAM_TOKEN", "")

    if not token:
        log.error("[BROADCAST] No Telegram token available")
        return {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0, "error": "No token"}

    # Load scan data for the message
    try:
        from nse_output import format_option_c

        scan_file = Path("telegram_last_scan.json")
        if not scan_file.exists():
            return {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0, "error": "No scan data"}
        with open(scan_file, encoding="utf-8") as f:
            data = json.load(f)
        stocks_list = data.get("stocks", [])
        scan_date = data.get("scan_date", "")
        if not stocks_list:
            return {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0, "error": "Empty scan data"}
        message = format_option_c(stocks_list, scan_date)
        if len(message) > 4096:
            message = message[:4050] + "\n\n<i>... truncated. Open Scanner App for full list.</i>"
    except Exception as e:
        log.exception(f"[BROADCAST] Failed to build message: {e}")
        return {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0, "error": str(e)}

    # Load all users
    users = _load_users()
    if not users:
        return {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0, "error": "No users registered"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent = 0
    failed = 0
    blocked = 0
    skipped = 0

    # Build morning keyboard
    try:
        from nse_output import build_morning_keyboard

        kb = build_morning_keyboard()
    except Exception:
        kb = None

    log.info(f"[BROADCAST] Starting — {len(users)} users")
    print(f"[BROADCAST] Sending to {len(users)} users...")

    import time

    for uid, udata in users.items():
        # Skip blocked users
        if udata.get("is_blocked", False):
            blocked += 1
            continue

        # Skip already-sent chat (admin)
        if skip_chat_id and int(uid) == int(skip_chat_id):
            skipped += 1
            continue

        try:
            payload = {
                "chat_id": uid,
                "text": message,
                "parse_mode": "HTML",
            }
            if kb:
                payload["reply_markup"] = json.dumps(kb)

            r = requests.post(url, data=payload, timeout=10)

            if r.status_code == 200:
                sent += 1
            elif r.status_code == 403:
                # User blocked the bot
                blocked += 1
                udata["is_blocked"] = True
                log.info(f"[BROADCAST] {uid} blocked the bot — marking")
            elif r.status_code == 429:
                # Rate limited — wait and retry once
                time.sleep(2)
                r2 = requests.post(url, data=payload, timeout=10)
                if r2.status_code == 200:
                    sent += 1
                else:
                    failed += 1
                    log.warning(f"[BROADCAST] {uid} retry failed: {r2.status_code}")
            else:
                failed += 1
                log.warning(f"[BROADCAST] {uid} failed: {r.status_code}")

        except Exception as e:
            failed += 1
            log.exception(f"[BROADCAST] {uid} error: {e}")

        # Rate limit: max 20 messages/sec (Telegram allows 30)
        time.sleep(0.05)

    # Save updated user data (blocked flags)
    _save_users(users)

    result = {
        "sent": sent,
        "failed": failed,
        "blocked": blocked,
        "skipped": skipped,
        "total": len(users),
    }
    log.info(f"[BROADCAST] Complete: {result}")
    print(f"[BROADCAST] Done — sent={sent} failed={failed} blocked={blocked} skipped={skipped}")
    return result


def format_broadcast_summary(result: dict) -> str:
    """Format broadcast result for admin confirmation message."""
    total = result.get("total", 0)
    sent = result.get("sent", 0)
    failed = result.get("failed", 0)
    blocked = result.get("blocked", 0)
    skipped = result.get("skipped", 0)

    if result.get("error"):
        return f"❌ <b>Broadcast Failed</b>\n\nReason: <code>{result['error']}</code>"

    return (
        f"✅ <b>Broadcast Complete</b>\n\n"
        f"📤 Sent:    <b>{sent}</b>\n"
        f"❌ Failed:  <b>{failed}</b>\n"
        f"🚫 Blocked: <b>{blocked}</b>\n"
        f"⏭ Skipped: <b>{skipped}</b>\n"
        f"👥 Total:   <b>{total}</b> registered users\n\n"
        f"<i>Blocked users auto-marked in user list.</i>"
    )


# ═══════════════════════════════════════════════════════════════
# PIPELINE CONFIRMATION — Sent at 6:05 AM after scan completes
# ═══════════════════════════════════════════════════════════════


def send_pipeline_confirmation(
    scan_date: str | None = None, stock_count: int = 0, prime_count: int = 0, run_time: str | None = None
) -> bool:
    """
    Send one-line pipeline confirmation to admin at 6:05 AM.
    Called from nse_output.generate_report() after successful scan.

    Args:
        scan_date:   'YYYY-MM-DD' string
        stock_count: total stocks in scan
        prime_count: number of Prime Entry stocks
        run_time:    time pipeline completed e.g. '6:02 AM IST'
    """
    token = (getattr(config, "TELEGRAM_TOKEN", None) if config else None) or os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = ADMIN_CHAT_ID
    if not token or not chat_id:
        return False

    try:
        sd = scan_date or date.today().strftime("%d-%b-%Y")
        rt = run_time or datetime.now().strftime("%I:%M %p IST")
        msg = (
            f"✅ <b>Pipeline Complete</b> — {sd}\n"
            f"📊 {stock_count} stocks · "
            f"🎯 {prime_count} Prime · "
            f"⏱ {rt}\n"
            f"<i>Send /broadcast to push to all users</i>"
        )
        kb = {"inline_keyboard": [[{"text": "📢 Broadcast to Users", "callback_data": "/broadcast"}]]}
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(
            url,
            data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "reply_markup": json.dumps(kb)},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        log.exception(f"[PIPELINE CONFIRM] {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NSE Bot Admin Tools")
    parser.add_argument("--health", action="store_true", help="Show health report")
    parser.add_argument("--users", action="store_true", help="Show user list")
    parser.add_argument("--send", action="store_true", help="Send health check to Telegram")
    parser.add_argument("--stats", action="store_true", help="Show activity stats")
    parser.add_argument("--broadcast", action="store_true", help="Broadcast today's scan to all users")
    args = parser.parse_args()

    if args.health:
        report = generate_health_report()
        msg = format_health_report(report)
        import re

        print(re.sub(r"<[^>]+>", "", msg))

    elif args.users:
        msg = format_user_list()
        import re

        print(re.sub(r"<[^>]+>", "", msg))

    elif args.send:
        ok = send_health_check()
        print(f"Health check sent: {ok}")

    elif args.stats:
        stats = get_activity_stats(days=1)
        print("Today's stats:")
        print(f"  Actions: {stats['total_actions']}")
        print(f"  Users:   {stats['unique_users']}")
        print(f"  Top actions: {stats['top_actions'][:5]}")

    elif args.broadcast:
        print("Starting broadcast...")
        result = broadcast_to_all_users()
        import re

        print(re.sub(r"<[^>]+>", "", format_broadcast_summary(result)))

    else:
        parser.print_help()
