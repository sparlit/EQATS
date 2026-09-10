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


"""
AWS Lambda entry point — Scanner function.

Triggered by:
  • EventBridge cron rules (Mon–Fri 10:30 AM IST + 4:00 PM IST)
  • API POST /scan (invoked async via boto3 from the API Lambda)

Event payload (from POST /scan):
  {
    "user_id":     "<uuid>",      # optional — scanner uses ADMIN_COGNITO_SUB if absent
    "cognito_sub": "<string>"     # informational only
  }
"""

import contextlib
import os
import sys
import uuid

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)


def handler(event: dict, context) -> dict:
    from scanner import run_scanner

    watchlists_dir = os.path.join(_here, "watchlists")
    user_id = None

    if isinstance(event, dict) and event.get("user_id"):
        with contextlib.suppress(ValueError):
            user_id = uuid.UUID(event["user_id"])

    print(f"[scanner_lambda] Starting scan. user_id={user_id}, dir={watchlists_dir}")
    run_scanner(watchlists_dir, user_id=user_id)
    return {"statusCode": 200, "body": "scan complete"}
