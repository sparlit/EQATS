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


"""Quick config validation script."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.config import get_settings

s = get_settings()

print("=" * 50)
print("RakshaQuant - Configuration Check")
print("=" * 50)

# Required
groq_ok = bool(s.groq_api_key)
print(f"Groq API Key:     {'[OK]' if groq_ok else '[MISSING]'}")

# Optional - DhanHQ
dhan_ok = bool(s.dhan_client_id and s.dhan_access_token)
print(f"DhanHQ API:       {'[OK]' if dhan_ok else '[Not configured - optional]'}")

# Free tier
print(f"\nData Source:      {s.market_data_source}")
print(f"Execution Mode:   {s.execution_mode}")
print(f"Paper Wallet:     Rs.{s.paper_wallet_balance:,.0f}")
print(f"News Analysis:    {'[Enabled]' if s.enable_news_analysis else '[Disabled]'}")

# Telegram
telegram_ok = bool(getattr(s, "telegram_bot_token", None) and getattr(s, "telegram_chat_id", None))
print(f"Telegram Alerts:  {'[OK]' if telegram_ok else '[Not configured - optional]'}")

# Cross-field validation warnings (live-mode creds, risk-param sanity, market hours, ...)
config_warnings = getattr(s, "config_warnings", [])
if config_warnings:
    print(f"\nConfiguration Warnings ({len(config_warnings)}):")
    for warning in config_warnings:
        print(f"  [WARN] {warning}")
else:
    print("\nConfiguration Warnings:  [None]")

print("\n" + "=" * 50)
if groq_ok:
    if config_warnings:
        print(f"[READY] System ready to run ({len(config_warnings)} config warning(s) above).")
    else:
        print("[READY] System ready to run!")
else:
    print("[ERROR] Please set GROQ_API_KEY in .env")
print("=" * 50)
