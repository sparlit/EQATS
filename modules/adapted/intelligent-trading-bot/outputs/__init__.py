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


from common.types import Venue


def get_trader_functions(venue: Venue) -> dict[str, callable]:
    """
    Return a dict of the four trader-related callables for the given venue.

    Example:
        funcs = get_trader_functions(Venue.BINANCE)
        funcs["trader"](...)
        funcs["update_order_status"](...)
    """
    if venue == venue.BINANCE:
        from outputs.trader_binance import (
            trader_binance,
        )
        from outputs.trader_binance import (
            update_account_balance as update_account_balance_binance,
        )
        from outputs.trader_binance import (
            update_order_status as update_order_status_binance,
        )
        from outputs.trader_binance import (
            update_trade_status as update_trade_status_binance,
        )

        return {
            "trader": trader_binance,
            "update_account_balance": update_account_balance_binance,
            "update_order_status": update_order_status_binance,
            "update_trade_status": update_trade_status_binance,
        }
    if venue == venue.MT5:
        from outputs.trader_mt5 import (
            trader_mt5,
        )
        from outputs.trader_mt5 import (
            update_account_balance as update_account_balance_mt5,
        )
        from outputs.trader_mt5 import (
            update_order_status as update_order_status_mt5,
        )
        from outputs.trader_mt5 import (
            update_trade_status as update_trade_status_mt5,
        )

        return {
            "trader": trader_mt5,
            "update_account_balance": update_account_balance_mt5,
            "update_order_status": update_order_status_mt5,
            "update_trade_status": update_trade_status_mt5,
        }
    msg = f"Unknown trader venue: {venue!r}"
    raise ValueError(msg)
