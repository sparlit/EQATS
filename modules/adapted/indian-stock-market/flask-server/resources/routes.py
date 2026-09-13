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


from .auth import LoginApi, SignupApi
from .history import History
from .search import Search
from .trade import AddTradeApi, PortfolioApi, TradesApi
from .watchlist import AddToWatchlist, CommonDetails, RemoveFromWatchlist, Watchlist


def initialize_routes(api):
    api.add_resource(SignupApi, "/api/auth/register")
    api.add_resource(LoginApi, "/api/auth/login")

    api.add_resource(AddTradeApi, "/api/add_to_portfolio")
    api.add_resource(TradesApi, "/api/trades")
    api.add_resource(PortfolioApi, "/api/portfolio_overview")

    api.add_resource(Watchlist, "/api/watchlist")
    api.add_resource(AddToWatchlist, "/api/watchlist/add/<code>", "/api/watchlist/add/<code>/<index>")
    api.add_resource(RemoveFromWatchlist, "/api/watchlist/remove/<code>")
    api.add_resource(CommonDetails, "/api/common_details")

    api.add_resource(Search, "/api/search/<searchStr>")

    api.add_resource(History, "/api/hist/<code>", "/api/hist/<code>/<exchange>")
