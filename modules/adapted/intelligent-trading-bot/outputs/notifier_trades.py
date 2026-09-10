import asyncio
import datetime
import logging
import os
import sys
from datetime import datetime as dt_class
from datetime import timedelta
from typing import Any, Dict, Optional

import pytz

try:
    import pandas as pd
    import pandas.api.types as ptypes
except ImportError:
    pd = None
    ptypes = None

import requests

try:
    from common.model_store import *
    from common.utils import *
    from service.App import *
except ImportError:
    pass

log = logging.getLogger("notifier")

logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("matplotlib").setLevel(logging.WARNING)


def is_ist_market_session_active(dt: dt_class | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else dt_class.now(ist)
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


async def trader_simulation(df: Any, model: dict[str, Any], config: dict[str, Any], model_store: Any) -> None:
    try:
        transaction = await generate_trader_transaction(df, model, config)
    except Exception as e:
        log.exception(f"Error in trader_simulation function: {e}")
        return
    if not transaction:
        return

    try:
        await send_transaction_message(transaction, config)
    except Exception as e:
        log.exception(f"Error in send_transaction_message function: {e}")
        return


async def generate_trader_transaction(df: Any, model: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    """
    Very simple trade strategy where we only buy and sell using the whole available amount
    """
    _ = config.get("symbol")
    get_transaction_path() if "get_transaction_path" in globals() else ""

    buy_signal_column = model.get("buy_signal_column")
    sell_signal_column = model.get("sell_signal_column")

    signal = get_signal(df, buy_signal_column, sell_signal_column) if "get_signal" in globals() else {}
    signal_side = signal.get("side")
    close_price = signal.get("close_price")
    close_time = signal.get("close_time")

    # Previous transaction: BUY (we are currently selling) or SELL (we are currently buying)
    if not hasattr(App, "transaction") or not App.transaction:
        t_status = None
        t_price = None
    else:
        t_status = App.transaction.get("status")
        t_price = App.transaction.get("price")

    if signal_side == "BUY" and (not t_status or t_status == "SELL"):
        profit = t_price - close_price if t_price else 0.0
        return {"timestamp": str(close_time), "price": close_price, "profit": profit, "status": "BUY"}
    if signal_side == "SELL" and (not t_status or t_status == "BUY"):
        profit = close_price - t_price if t_price else 0.0
        return {"timestamp": str(close_time), "price": close_price, "profit": profit, "status": "SELL"}
    return None


async def send_transaction_message(transaction: dict[str, Any], config: dict[str, Any]) -> None:
    """Placeholder for sending transaction message."""


def get_transaction_path() -> str:
    """Placeholder for getting transaction path."""
    return ""


def get_signal(df: Any, buy_col: str | None, sell_col: str | None) -> dict[str, Any]:
    """Placeholder for getting signal from dataframe."""
    return {"side": None, "close_price": 0.0, "close_time": dt_class.now()}


class App:
    transaction: dict[str, Any] | None = None


class ModelStore:
    pass
