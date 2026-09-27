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
Standalone daily check: is today's Kite access token still valid? Run
once each morning (nse-token-check.timer, ~07:00 IST -- well after
Kite's ~6 AM daily token reset and well before the 09:16 gap-check needs
a working session) and pushes a notification with a direct link to the
dashboard if it's expired, so there's time to log in before market open
instead of only discovering it when a scheduled job fails.

Doesn't touch state_db.job_runs -- this isn't a rebalance/gap-check/
fundamentals job, just a proactive heads-up. See state_db.job_run()'s
own TokenException handling for the safety-net case where a scheduled
job discovers an expired token mid-run instead (covers this check not
having run, or the token expiring/getting revoked later in the day).
"""


import datetime as dt

import kite_client
import notify
import state_db
from kiteconnect.exceptions import TokenException

import config


def _alert():
    print(f"{dt.datetime.now():%d %b %Y %H:%M:%S} Kite token EXPIRED -- sending push notification.")
    title = "KK Trading -- Kite login needed"
    message = "Today's Kite session has expired. Log in before the 09:16 gap-check / market open."
    for dead in notify.send_webpush_all(state_db.get_push_subscriptions(), title, message, notify.DASHBOARD_URL):
        state_db.delete_push_subscription(dead)


def main():
    if not config.KITE_ACCESS_TOKEN:
        _alert()
        return
    try:
        kite_client.get_kite().profile()
        print(f"{dt.datetime.now():%d %b %Y %H:%M:%S} Kite token OK.")
    except TokenException:
        _alert()
    except Exception as e:
        print(
            f"{dt.datetime.now():%d %b %Y %H:%M:%S} Token check itself failed (not necessarily an expired token): {e}"
        )


if __name__ == "__main__":
    main()
