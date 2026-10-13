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


# broker/hdfcsecurities/api/baseurl.py
#
# Central place for HDFC Securities (InvestRight) hosts and the auth-header
# builder.
#
# InvestRight auth specifics (from the official docs):
#   - `Authorization: <access_token>` -- NO "Bearer " prefix.
#   - `User-Agent` is MANDATORY on essentially every request; requests without
#     it are rejected.
#   - Every authenticated endpoint additionally requires the app's `api_key` as
#     a QUERY param (not a header).
#
# InvestRight and HDFC Sky are two different products from the same house that
# share this gateway design and the GenericDTO market-data proto, but they are
# separate hosts, separate apps and separate credentials. Nothing here imports
# from broker.hdfcsky.
#
# Unlike HDFC Sky, no InvestRight endpoint takes a `client_id` -- the account is
# implied by the access token throughout -- so there is deliberately no
# client-id helper here.

import os
from urllib.parse import urlencode

# REST host ---------------------------------------------------------------
ROOT_URL = "https://developer.hdfcsec.com"

# WebSocket market-data feed (protobuf GenericDTO frames).
WS_MARKET_DATA_PATH = "/wsapi/v1/session"

# Security master: a plain CSV (public, unauthenticated -- no api_key, no
# Authorization header, no User-Agent needed).
SECURITY_MASTER_URL = f"{ROOT_URL}/oapi/v1/security-master"

# The docs' sample User-Agent. InvestRight rejects requests without one.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def get_root_url():
    return ROOT_URL


def get_ws_url(auth_token):
    """WebSocket URL for the market-data feed.

    The feed gateway authenticates on the query string: the access token as
    `token` (NOT `access_token`) together with the app `api_key`, matching the
    sibling InvestRight/Sky gateway.
    """
    host = get_root_url().replace("https://", "wss://").replace("http://", "ws://")
    query = urlencode({"token": auth_token, "api_key": get_api_key()})
    return f"{host}{WS_MARKET_DATA_PATH}?{query}"


def get_hdfcsecurities_headers(auth_token, with_json=False):
    """Build the standard InvestRight request headers.

    Args:
        auth_token: the access token stored in the Auth table.
        with_json: set True for requests that carry a JSON body.
    """
    headers = {
        "Authorization": auth_token,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers


def get_api_key():
    return os.getenv("BROKER_API_KEY")


def base_params():
    """Query params every authenticated call needs.

    InvestRight only ever documents `api_key` here -- unlike HDFC Sky, no
    endpoint takes `client_id` as a query param (the account is implied by the
    access token).
    """
    return {"api_key": get_api_key()}
