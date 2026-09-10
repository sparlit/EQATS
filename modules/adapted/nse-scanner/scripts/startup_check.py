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


"""Fail-fast CI startup validation without starting the long-running bot."""

import json
import os
from pathlib import Path

import requests


def main() -> int:
    errors: list[str] = []
    routes = {
        "V3": ("V3_TELEGRAM_BOT_TOKEN", "V3_TELEGRAM_CHAT_ID"),
        "LADDER": ("LADDER_TELEGRAM_BOT_TOKEN", "LADDER_TELEGRAM_CHAT_ID"),
        "HULL": ("HULL_TELEGRAM_BOT_TOKEN", "HULL_TELEGRAM_CHAT_ID"),
    }
    for filename in ("telegram_last_scan.json", "scan_history.json"):
        path = Path(filename)
        if not path.exists():
            errors.append(f"{filename} missing")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{filename} invalid: {exc}")
    for route, (token_name, chat_name) in routes.items():
        token = os.getenv(token_name, "").strip()
        chat_id = os.getenv(chat_name, "").strip()
        if not token:
            errors.append(f"{token_name} missing")
            continue
        if not chat_id:
            errors.append(f"{chat_name} missing")
        try:
            response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
            if response.status_code != 200 or not response.json().get("ok"):
                errors.append(f"{route} Telegram getMe failed: HTTP {response.status_code}")
        except requests.RequestException as exc:
            errors.append(f"{route} Telegram getMe unavailable: {exc}")
    if errors:
        print("STARTUP CHECK FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("STARTUP CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
