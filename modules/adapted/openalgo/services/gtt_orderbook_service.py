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


import importlib
from typing import Any

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

logger = get_logger(__name__)

API_TYPE = "gttorderbook"


def import_broker_gtt_module(broker_name: str) -> Any | None:
    try:
        return importlib.import_module(f"broker.{broker_name}.api.gtt_api")
    except ImportError as error:
        logger.error(f"Error importing GTT module for broker '{broker_name}': {error}")
        return None


def _active_first(response: dict[str, Any]) -> dict[str, Any]:
    """Put triggers that can still fire ahead of history.

    A stable sort, so each group keeps the newest-first order the source gave
    it. Applied to both the sandbox and the broker books so the tab reads the
    same way in either mode.
    """
    data = response.get("data")
    if isinstance(data, list):
        response["data"] = sorted(
            data, key=lambda gtt: (gtt.get("status") or "").lower() != "active"
        )
    return response


def get_gtt_orderbook_with_auth(
    auth_token: str,
    broker: str,
    original_data: dict[str, Any] | None = None,
    include_history: bool = False,
) -> tuple[bool, dict[str, Any], int]:
    # Analyze (sandbox) mode reads the sandbox GTT book. Gated on original_data
    # because that is where the API key lives, and the sandbox book is per-user.
    if get_analyze_mode() and original_data:
        from services.sandbox_service import sandbox_gtt_orderbook

        success, response, status_code = sandbox_gtt_orderbook(
            original_data.get("apikey", ""),
            status_filter=None if include_history else "active",
        )
        return success, (_active_first(response) if success else response), status_code

    broker_module = import_broker_gtt_module(broker)
    if broker_module is None:
        return (
            False,
            {
                "status": "error",
                "message": f"GTT orders are not supported for broker '{broker}' yet",
            },
            501,
        )

    try:
        response_data, status_code = broker_module.get_gtt_book(
            auth_token, include_history=include_history
        )
    except Exception as e:
        logger.exception(f"Error in broker_module.get_gtt_book: {e}")
        return False, {"status": "error", "message": str(e)}, 500

    if status_code != 200:
        return False, response_data, status_code

    return True, _active_first(response_data), 200


def get_gtt_orderbook(
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
    status: str = "active",
) -> tuple[bool, dict[str, Any], int]:
    # ``status`` is the request field: ``active`` (default) or ``all``.
    include_history = (status or "active").lower() == "all"

    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return get_gtt_orderbook_with_auth(
            AUTH_TOKEN, broker_name, {"apikey": api_key}, include_history=include_history
        )

    if auth_token and broker:
        return get_gtt_orderbook_with_auth(
            auth_token, broker, None, include_history=include_history
        )

    return (
        False,
        {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        },
        400,
    )
