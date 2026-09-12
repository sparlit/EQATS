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
nse_admin_report.py — Daily Admin Reports via Railway Cron
==========================================================
Standalone script — no bot process needed.
Railway cron triggers this at 11:30 PM and 11:35 PM IST.

Two reports sent to ADMIN_CHAT_ID only:

  11:30 PM IST (18:00 UTC) — Health Check
    Scan freshness, DB status, user count,
    tracker signals, last pipeline run

  11:35 PM IST (18:05 UTC) — User Report
    Total users, active today, new today,
    top actions, most active user

Railway Cron Setup:
  Service:  nse-admin-cron  (or add to nse-pipeline)
  Command:  python nse_admin_report.py --health
  Schedule: 0 18 * * 1-5   (11:30 PM IST weekdays)

  Command:  python nse_admin_report.py --users
  Schedule: 5 18 * * 1-5   (11:35 PM IST weekdays)

Usage:
  python nse_admin_report.py --health   # send health check
  python nse_admin_report.py --users    # send user report
  python nse_admin_report.py --both     # send both
  python nse_admin_report.py --preview  # print without sending
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

try:
    import requests
except ImportError:
    print("[ERROR] Missing dependency: requests")
    print("[HINT] Install dependencies: pip install -r requirements.txt")
    sys.exit(1)
from datetime import datetime

# ── Env setup ─────────────────────────────────────────────
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
ADMIN_CHATID = (os.environ.get("ADMIN_CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
DB_PATH = os.environ.get("DB_PATH", "nse_scanner.db")

_HERE = Path(__file__).parent


# ═══════════════════════════════════════════════════════════
# SEND HELPER
# ═══════════════════════════════════════════════════════════


def _send(text: str) -> bool:
    """Send message to admin chat only."""
    if not TOKEN or not ADMIN_CHATID:
        print("[WARN] TOKEN or ADMIN_CHATID not set")
        return False
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(
            url,
            data={
                "chat_id": ADMIN_CHATID,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if r.status_code == 200:
            print("[SENT] Message delivered to admin")
            return True
        print(f"[FAIL] {r.status_code}: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


# ═══════════════════════════════════════════════════════════
# DATA LOADERS
# ═══════════════════════════════════════════════════════════


def _load_scan() -> dict:
    f = _HERE / "telegram_last_scan.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_history() -> list:
    f = _HERE / "scan_history.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("history", [])
    except Exception:
        return []

    f = _HERE / "bot_users.json"
    fallback = _HERE / "user_data.json"
    if not f.exists() and not fallback.exists():
        return {}
    try:
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        data = json.loads(fallback.read_text(encoding="utf-8"))
        # legacy format: {"users":[{"id":...,"name":...}]}
        users = {}
        for u in data.get("users", []):
            uid = str(u.get("id", "")).strip()
            if not uid:
                continue
            users[uid] = {
                "user_id": uid,
                "username": "",
                "full_name": u.get("name", "") or uid,
                "first_seen": u.get("join_date", ""),
                "last_seen": u.get("last_active", ""),
                "total_visits": 0,
                "daily_visits": {},
                "is_blocked": False,
            }
        return users
    except Exception:
        return {}


def _load_tracker() -> dict:
    f = _HERE / "signal_tracker.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _db_info() -> dict:
    info = {"ok": False, "size_mb": 0, "price_rows": 0, "date_range": "", "last_load": ""}
    try:
        db = Path(DB_PATH)
        if not db.exists():
            return info
        info["size_mb"] = round(db.stat().st_size / 1_048_576, 1)
        conn = sqlite3.connect(str(db))
        try:
            r = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM daily_prices").fetchone()
            info["price_rows"] = r[0] or 0
            if r[1] and r[2]:
                info["date_range"] = f"{r[1]} → {r[2]}"
            # Last load from load_log
            ll = conn.execute("SELECT date, loaded_at FROM load_log ORDER BY date DESC LIMIT 1").fetchone()
            if ll:
                info["last_load"] = f"{ll[0]} at {ll[1][:16]}"
            info["ok"] = True
        finally:
            conn.close()
    except Exception as e:
        info["error"] = str(e)
    return info


def _activity_today() -> dict:
    """Parse today's activity from bot_activity.log."""
    log_file = _HERE / "logs" / "bot_activity.log"
    if not log_file.exists():
        return {"actions": 0, "users": set(), "top": []}
    try:
        today = date.today().isoformat()
        actions = {}
        users = set()
        with open(log_file, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if today not in line:
                    continue
                if "user=" in line:
                    uid = line.split("user=")[1].split(" ")[0]
                    users.add(uid)
                if "action=" in line:
                    act = line.split("action=")[1].strip()
                    actions[act] = actions.get(act, 0) + 1
        top = sorted(actions.items(), key=lambda x: x[1], reverse=True)
        return {
            "actions": sum(actions.values()),
            "users": users,
            "top": top[:5],
        }
    except Exception:
        return {"actions": 0, "users": set(), "top": []}


# ═══════════════════════════════════════════════════════════
# HEALTH CHECK REPORT
# ═══════════════════════════════════════════════════════════


def build_health_report() -> str:
    """
    Build health check message.
    Sent to admin at 11:30 PM IST every weekday.
    """
    now = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    today = date.today().isoformat()

    # Scan status
    scan = _load_scan()
    stocks = scan.get("stocks", [])
    scan_date = scan.get("scan_date", "")
    total = len(stocks)
    prime = sum(1 for s in stocks if s.get("situation") == "prime")
    hold = sum(1 for s in stocks if s.get("situation") == "hold")
    watch = sum(1 for s in stocks if s.get("situation") == "watch")
    avoid = sum(1 for s in stocks if s.get("situation") == "avoid")

    scan_age = ""
    scan_icon = "❓"
    if scan_date:
        try:
            sd = datetime.strptime(scan_date, "%Y-%m-%d").date()
            age = (date.today() - sd).days
            if age == 0:
                scan_icon = "✅"
                scan_age = "Today"
            elif age == 1:
                scan_icon = "⚠️"
                scan_age = "Yesterday"
            else:
                scan_icon = "❌"
                scan_age = f"{age} days old"
        except Exception:
            scan_age = scan_date

    # DB
    db = _db_info()
    db_icon = "✅" if db["ok"] else "❌"

    # History
    hist = _load_history()
    hist_days = len(hist)

    # Tracker
    tracker = _load_tracker()
    active_sig = len(tracker.get("signals", {}))

    # Users
    users = _load_users()
    user_count = len(users)
    active_today = sum(1 for u in users.values() if u.get("daily_visits", {}).get(today, 0) > 0)

    # Last user activity
    last_seen = ""
    if users:
        try:
            latest = max(users.values(), key=lambda u: u.get("last_seen", ""))
            ls = latest.get("last_seen", "")[:16]
            ln = latest.get("full_name", "") or latest.get("username", "")
            last_seen = f"{ln} at {ls}" if ln else ls
        except Exception:
            pass

    msg = "🏥 <b>NSE Bot Health Check</b>\n"
    msg += f"<i>{now}</i>\n"
    msg += "━" * 22 + "\n\n"

    msg += "<b>📊 Scan</b>\n"
    msg += f"  {scan_icon} Date: <b>{scan_date or 'No data'}</b> ({scan_age})\n"
    msg += f"  📈 Stocks: <b>{total}</b>\n"
    msg += f"  🎯 {prime} Prime · 💰 {hold} Hold · 👀 {watch} Watch · 🚫 {avoid} Avoid\n\n"

    msg += "<b>🗄️ Database</b>\n"
    msg += f"  {db_icon} Size: <b>{db['size_mb']} MB</b>\n"
    if db["ok"]:
        msg += f"  📋 Rows: {db['price_rows']:,}\n"
        msg += f"  📅 Range: {db['date_range']}\n"
        msg += f"  ⏱ Last load: {db['last_load']}\n\n"
    else:
        msg += f"  ❌ DB Error: {db.get('error', 'unknown')}\n\n"

    msg += "<b>📚 History & Tracker</b>\n"
    msg += f"  📜 History: <b>{hist_days} days</b> stored\n"
    msg += f"  🎯 Active signals: <b>{active_sig}</b>\n\n"

    msg += "<b>👥 Users</b>\n"
    msg += f"  Total: <b>{user_count}</b>\n"
    msg += f"  Active today: <b>{active_today}</b>\n"
    if last_seen:
        msg += f"  Last seen: {last_seen}\n"

    msg += "\n━" * 22 + "\n"
    msg += "<i>Send /broadcast to push scan to all users</i>"

    return msg


# ═══════════════════════════════════════════════════════════
# USER REPORT
# ═══════════════════════════════════════════════════════════


def build_user_report() -> str:
    """
    Build daily user report.
    Sent to admin at 11:35 PM IST every weekday.
    """
    now = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    today = date.today().isoformat()

    users = _load_users()
    total = len(users)
    activity = _activity_today()

    # Active today
    active_today = [u for u in users.values() if u.get("daily_visits", {}).get(today, 0) > 0]

    # New today (first seen today)
    new_today = [u for u in users.values() if u.get("first_seen", "")[:10] == today]

    # Most active user today
    most_active = None
    if active_today:
        most_active = max(active_today, key=lambda u: u.get("daily_visits", {}).get(today, 0))

    # Blocked users
    blocked = [u for u in users.values() if u.get("is_blocked", False)]

    # 7-day active users
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    active_7d = sum(1 for u in users.values() if u.get("last_seen", "")[:10] >= week_ago)

    msg = "👥 <b>Daily User Report</b>\n"
    msg += f"<i>{now}</i>\n"
    msg += "━" * 22 + "\n\n"

    msg += "<b>📊 Overview</b>\n"
    msg += f"  Total registered: <b>{total}</b>\n"
    msg += f"  Active today:     <b>{len(active_today)}</b>\n"
    msg += f"  New today:        <b>{len(new_today)}</b>\n"
    msg += f"  Active 7 days:    <b>{active_7d}</b>\n"
    msg += f"  Blocked:          <b>{len(blocked)}</b>\n\n"

    if new_today:
        msg += "<b>🆕 New Users Today</b>\n"
        for u in new_today[:5]:
            name = u.get("full_name", "") or u.get("username", "") or u.get("user_id", "")
            msg += f"  • {name}\n"
        if len(new_today) > 5:
            msg += f"  ... +{len(new_today) - 5} more\n"
        msg += "\n"

    if activity["actions"] > 0:
        msg += "<b>⚡ Today's Activity</b>\n"
        msg += f"  Total actions: <b>{activity['actions']}</b>\n"
        msg += f"  Unique users:  <b>{len(activity['users'])}</b>\n"
        if activity["top"]:
            msg += "\n  Top commands:\n"
            for act, count in activity["top"]:
                msg += f"  {count:>4}×  {act}\n"
        msg += "\n"

    if most_active:
        name = most_active.get("full_name", "") or most_active.get("username", "") or most_active.get("user_id", "")
        visits = most_active.get("daily_visits", {}).get(today, 0)
        msg += "<b>🏆 Most Active Today</b>\n"
        msg += f"  {name} — {visits} actions\n\n"

    if active_today:
        msg += "<b>👤 Active Users Today</b>\n"
        for u in sorted(active_today, key=lambda x: x.get("daily_visits", {}).get(today, 0), reverse=True)[:8]:
            name = u.get("full_name", "") or u.get("username", "") or u.get("user_id", "")
            visits = u.get("daily_visits", {}).get(today, 0)
            msg += f"  • {name} ({visits}×)\n"
        if len(active_today) > 8:
            msg += f"  ... +{len(active_today) - 8} more\n"

    msg += "\n━" * 22 + "\n"
    msg += "<i>Tomorrow's scan at 6:00 AM IST</i>"

    return msg


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="NSE Admin Daily Reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Railway Cron Schedule (UTC):
  Health check:  0 18 * * 1-5   (11:30 PM IST weekdays)
  User report:   5 18 * * 1-5   (11:35 PM IST weekdays)

Examples:
  python nse_admin_report.py --health
  python nse_admin_report.py --users
  python nse_admin_report.py --both
  python nse_admin_report.py --preview
        """,
    )
    parser.add_argument("--health", action="store_true", help="Send health check to admin")
    parser.add_argument("--users", action="store_true", help="Send user report to admin")
    parser.add_argument("--both", action="store_true", help="Send both reports")
    parser.add_argument("--preview", action="store_true", help="Print reports without sending")
    args = parser.parse_args()

    if not any([args.health, args.users, args.both, args.preview]):
        parser.print_help()
        return

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] NSE Admin Report")
    print(f"TOKEN: {'SET' if TOKEN else 'NOT SET'}")
    print(f"ADMIN: {ADMIN_CHATID or 'NOT SET'}")

    if args.preview:
        import re

        def strip(t):
            return re.sub(r"<[^>]+>", "", t)

        print("\n" + "=" * 50)
        print("HEALTH CHECK:")
        print("=" * 50)
        print(strip(build_health_report()))
        print("\n" + "=" * 50)
        print("USER REPORT:")
        print("=" * 50)
        print(strip(build_user_report()))
        return

    if args.health or args.both:
        print("\n[HEALTH] Building report...")
        msg = build_health_report()
        ok = _send(msg)
        print(f"[HEALTH] {'✅ Sent' if ok else '❌ Failed'}")

    if args.users or args.both:
        print("\n[USERS] Building report...")
        msg = build_user_report()
        ok = _send(msg)
        print(f"[USERS] {'✅ Sent' if ok else '❌ Failed'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
