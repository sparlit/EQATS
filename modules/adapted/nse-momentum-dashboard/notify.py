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
Browser push notifications (Web Push API, see static/sw.js, push_server.py).
Used to alert when today's Kite session has expired and needs a fresh
login (see check_kite_token.py, and state_db.job_run()'s TokenException
handling) -- that's the one thing this app can never automate away,
since Zerodha's OAuth login + 2FA needs an actual human -- plus a
completion push after the scheduled rebalance scan.

Deliberately reads its settings straight from the environment (its own
load_dotenv(), not `import config`) rather than depending on config.py,
which itself imports state_db -- state_db.py imports this module for
the job_run() safety net below, so depending on config here would
create an import cycle (state_db -> notify -> config -> state_db).
"""


import json
import os

from dotenv import load_dotenv
from pywebpush import WebPushException, webpush

load_dotenv()

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

# VAPID_PRIVATE_KEY is the raw url-safe-base64 32-byte EC private key
# pywebpush accepts directly (no PEM file needed); VAPID_PUBLIC_KEY is the
# matching uncompressed-point public key the browser's
# PushManager.subscribe() needs -- safe to expose client-side, that's the
# point of it being the "public" half. Generate a pair with:
#   python -c "from py_vapid import Vapid02; import base64; v=Vapid02(); \
#     v.generate_keys(); pn=v.private_key.private_numbers(); \
#     pub=v.public_key.public_numbers(); \
#     print('VAPID_PRIVATE_KEY=' + base64.urlsafe_b64encode(pn.private_value.to_bytes(32,'big')).rstrip(b'=').decode()); \
#     print('VAPID_PUBLIC_KEY=' + base64.urlsafe_b64encode(b'\x04'+pub.x.to_bytes(32,'big')+pub.y.to_bytes(32,'big')).rstrip(b'=').decode())"
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "")

# push_server.py's own port -- dashboard.py's JS derives the full URL from
# this plus the page's own hostname (window.location.hostname), so no
# separate PUSH_SERVER_URL env var is needed.
PUSH_SERVER_PORT = os.getenv("PUSH_SERVER_PORT", "8503")


def send_webpush_all(
    subscriptions: list[dict], title: str, message: str, url: str | None = None
) -> list[str]:
    """Sends to every subscription in the pywebpush subscription_info shape
    (see state_db.get_push_subscriptions()). Returns the endpoints found
    dead (410 Gone / 404 -- the device uninstalled the app or revoked
    notifications outside this app) so the caller can delete them from
    state_db; a subscription failing for any OTHER reason (network blip,
    the push service being briefly down) is left alone so a transient
    error doesn't silently unsubscribe a still-valid device.

    No-op (returns []) if VAPID keys aren't configured, or there are no
    subscriptions -- notifications are optional, never a hard dependency
    for anything that calls this."""
    if not VAPID_PRIVATE_KEY or not subscriptions:
        return []
    payload = json.dumps({"title": title, "message": message, "url": url or ""})
    dead = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL or 'admin@localhost'}"},
                # pywebpush defaults ttl=0, which tells the push service
                # (FCM etc.) to drop the message outright if the device
                # isn't reachable RIGHT NOW rather than queuing it for
                # when it reconnects -- confirmed live 2026-08-05: the
                # 07:00 token-expiry push sent successfully (no error
                # here) but was never received because the phone's data
                # was off at that exact moment, and turning data back on
                # later didn't deliver it, since FCM had already discarded
                # it. A device that's online when this is called still
                # gets it immediately either way -- ttl only changes what
                # happens in the offline case. 12h covers a full trading
                # day (this fires at 07:00, well before market open).
                ttl=12 * 3600,
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                dead.append(sub["endpoint"])
            else:
                print(f"[notify] webpush failed ({status}): {e}")
        except Exception as e:
            print(f"[notify] webpush failed: {e}")
    return dead
