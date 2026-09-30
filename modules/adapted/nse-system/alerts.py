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
Unified alerts — Telegram text, photo, daily report, swing setup,
all-weather setup.

Canonical module (ID7 consolidation, 2026-09-12). Replaces the split
between telegram_alerts.py and swing_alerts.py. Both of those remain
as thin re-export shims for backwards compatibility.

Credentials resolution:
  1. env TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
  2. data/tg_secret.txt (line 1 = token, line 2 = chat_id)
"""
import datetime as dt
import os

import requests

SECRET = "data/tg_secret.txt"


def _creds():
    token = os.getenv("TELEGRAM_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        return token, chat
    try:
        with open(SECRET) as f:
            lines = [l.strip() for l in f if l.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    except Exception as e:
        print(f"[ALERTS] secret file unavailable: {e}")
    return None, None


def send(text):
    """Send a text message. Returns True on 200."""
    token, chat = _creds()
    if not token or not chat:
        print("[ALERTS] no telegram creds configured")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=15
        )
        print(f"[ALERTS] text -> {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"[ALERTS] send failed: {e}")
        return False


def send_photo(path, caption=""):
    """Send a photo file with caption. Returns True on 200."""
    token, chat = _creds()
    if not token or not chat:
        return False
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat, "caption": caption},
                files={"photo": f},
                timeout=30,
            )
        print(f"[ALERTS] photo -> {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"[ALERTS] photo failed: {e}")
        return False


def report():
    """Daily system report (scan, recommended, top ML)."""
    import db

    conn = db.get_conn()
    try:
        last = conn.execute("SELECT MAX(scan_date) FROM scan_results").fetchone()
        last = last[0] if last else None
        lines = ["📊 NSE SYSTEM DAILY REPORT", f"Scan date: {last or '—'}"]
        if last:
            passed = conn.execute(
                "SELECT COUNT(*) FROM scan_results WHERE scan_date=? AND passed=1", (last,)
            ).fetchone()[0]
            lines.append(f"Passed gates: {passed}")
        rec = conn.execute("SELECT symbol FROM pipeline WHERE status='Recommended' LIMIT 10").fetchall()
        lines.append("RECOMMENDED: " + (", ".join(r[0] for r in rec) if rec else "none"))
        top = conn.execute(
            "SELECT symbol, final_ml_score FROM ml_predictions ORDER BY final_ml_score DESC LIMIT 5"
        ).fetchall()
        if top:
            lines.append("TOP ML: " + ", ".join(f"{s} {v:.0f}" for s, v in top))
        # swing summary
        try:
            sw = conn.execute("SELECT outcome, COUNT(*) FROM swing_signals GROUP BY outcome").fetchall()
            if sw:
                lines.append("SWING: " + ", ".join(f"{k}={v}" for k, v in sw))
        except Exception:
            pass
        send("\n".join(lines))
    except Exception as e:
        print(f"[ALERTS] report failed: {e}")
    finally:
        conn.close()


def notify_setup(st):
    """Swing setup alert. `st` is a Setup object from setup.SetupDetector."""
    try:
        import fund_veto

        bad, why = fund_veto.vetoed(st.symbol)
        if bad:
            send(f"🚫 FUND VETO {st.symbol} — setup suppressed\nreason: {why}\n(not tradeable under fundamental gate)")
            print(f"[ALERTS] {st.symbol} vetoed: {why}")
            return False
    except Exception as e:
        print(f"[ALERTS] veto check skipped: {e}")

    risk = ((st.entry_price - st.stop_loss) / st.entry_price) * 100 if st.entry_price else 0
    text = (
        f"🏄 NEW SETUP {st.symbol}\n"
        f"Trigger  ₹{st.entry_price}\n"
        f"PDL Stop ₹{st.stop_loss}\n"
        f"Target   ₹{st.target_price}\n"
        f"Risk {risk:.1f}% · PB {st.pullback_depth * 100:.0f}%\n"
        f"Shape {st.shape_score}/100 · Zone {st.ema_proximity}"
    )
    ok = send(text)
    try:
        import chart_img

        path = chart_img.render(
            st.symbol, setup={"trigger": st.entry_price, "stop": st.stop_loss, "target": st.target_price}
        )
        if path:
            send_photo(path, caption=f"📊 {st.symbol} setup chart")
    except Exception as e:
        print(f"[ALERTS] chart snapshot skipped: {e}")
    return ok


def notify_all_weather(sym, st):
    """All-weather setup alert (DEFENSIVE regime, half size)."""
    try:
        import fund_veto

        bad, why = fund_veto.vetoed(sym)
        if bad:
            send(f"🚫 AW VETO {sym} — {why}")
            return False
    except Exception:
        pass

    risk = st["risk_pct"] * 100
    text = (
        f"🌧️ ALL-WEATHER SETUP {sym}\n"
        f"Pattern: {st['pattern']}\n"
        f"Quality: {st.get('tier', 'UNK')}  "
        f"(fund {st.get('fund_score') or '—'} · "
        f"roce {st.get('roce') or '—'})\n"
        f"Trigger  ₹{st['entry']}\n"
        f"Stop     ₹{st['stop']}\n"
        f"Target   ₹{st['target']} (2R)\n"
        f"Risk {risk:.1f}%\n"
        f"⚠️ DEFENSIVE regime — use HALF position size"
    )
    ok = send(text)
    try:
        import chart_img

        path = chart_img.render(sym, setup={"trigger": st["entry"], "stop": st["stop"], "target": st["target"]})
        if path:
            send_photo(path, caption=f"📊 {sym} ALL-WEATHER chart")
    except Exception as e:
        print(f"[ALERTS] AW chart skipped: {e}")
    return ok


if __name__ == "__main__":
    ok = send("🟢 NSE Intelligence — unified alerts channel test")
    print("sent" if ok else "check logs above")
