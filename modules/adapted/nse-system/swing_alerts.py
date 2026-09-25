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


"""Telegram alerts for swing setups — text first, chart snapshot second.
Chart layer is optional: if it fails, the text alert still goes out."""
import os


def send(text):
    # Primary: existing telegram_alerts (secret file / env)
    try:
        import telegram_alerts

        telegram_alerts.send(text)
        return True
    except Exception as e:
        print(f"[ALERT] telegram_alerts failed: {e}")
    # Fallback: env-based
    try:
        import requests
        from dotenv import load_dotenv

        load_dotenv()
        token = os.getenv("TELEGRAM_TOKEN")
        chat = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat:
            print("[ALERT] telegram creds missing")
            return False
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[ALERT] send failed: {e}")
        return False


def notify_setup(st):
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
        import telegram_alerts

        path = chart_img.render(
            st.symbol, setup={"trigger": st.entry_price, "stop": st.stop_loss, "target": st.target_price}
        )
        if path:
            telegram_alerts.send_photo(path, caption=f"📊 {st.symbol} setup chart")
    except Exception as e:
        print(f"[ALERT] chart snapshot skipped: {e}")
    return ok


if __name__ == "__main__":
    ok = send("🟢 NSE Intelligence Terminal — alert channel test")
    print("sent" if ok else "check logs above")
