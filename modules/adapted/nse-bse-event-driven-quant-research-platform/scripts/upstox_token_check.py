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


#!/usr/bin/env python3
"""Quick Upstox token health check.

Shows: validity, expiry time, remaining hours, user info.

Usage:
  python scripts/upstox_token_check.py
"""


import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "upstox_tokens.json"


def main() -> int:
    if not TOKEN_FILE.exists():
        print("ERROR: upstox_tokens.json not found")
        return 1

    data = json.loads(TOKEN_FILE.read_text())
    access_token = data.get("access_token", "")
    extended_token = data.get("extended_token", "")

    if not access_token:
        print("ERROR: No access_token in file")
        return 1

    # Decode access token JWT
    now = time.time()
    print(f"User:      {data.get('user_name', 'N/A')} ({data.get('user_id', 'N/A')})")
    print(f"Email:     {data.get('email', 'N/A')}")
    print(f"Broker:    {data.get('broker', 'N/A')}")
    print()

    try:
        parts = access_token.split(".")
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        exp = decoded.get("exp", 0)
        iat = decoded.get("iat", 0)
        remaining_h = (exp - now) / 3600
        remaining_m = remaining_h * 60

        print("Access Token:")
        print(f"  Issued:    {datetime.fromtimestamp(iat, tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  Expires:   {datetime.fromtimestamp(exp, tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}")
        if remaining_h > 0:
            print(f"  Remaining: {remaining_h:.1f}h ({remaining_m:.0f} min)")
            print("  Status:    VALID")
        else:
            print(f"  Remaining: EXPIRED {-remaining_h:.1f}h ago")
            print("  Status:    EXPIRED")
    except Exception as e:
        print(f"  JWT decode error: {e}")

    print()

    # Decode extended token
    if extended_token:
        try:
            parts = extended_token.split(".")
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            exp = decoded.get("exp", 0)
            remaining_d = (exp - now) / 86400

            print("Extended Token:")
            print(
                f"  Expires:   {datetime.fromtimestamp(exp, tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}"
            )
            print(f"  Remaining: {remaining_d:.0f} days")
            if remaining_d > 30:
                print("  Status:    OK")
            elif remaining_d > 0:
                print("  Status:    WARNING — expiring soon")
            else:
                print("  Status:    EXPIRED — need full re-login")
        except Exception as e:
            print(f"  JWT decode error: {e}")
    else:
        print("Extended Token: NONE")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
