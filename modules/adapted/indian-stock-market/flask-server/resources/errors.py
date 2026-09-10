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


InternalServerError = {"error": "Something went wrong"}

SchemaValidationError = {"error": "Request is missing required fields"}

EmailAlreadyExistsError = {"error": "User with given email address/username already exists"}

UnauthorizedError = {"error": "Invalid username or password"}

errors = {
    "SchemaValidationError": {"message": "Request is missing required fields", "status": 400},
    "UpdatingMovieError": {"message": "Updating movie added by other is forbidden", "status": 403},
    "DeletingMovieError": {"message": "Deleting movie added by other is forbidden", "status": 403},
    "MovieNotExistsError": {"message": "Movie with given id doesn't exists", "status": 400},
    "EmailAlreadyExistsError": {"message": "User with given email address already exists", "status": 400},
    "UnauthorizedError": {"message": "Invalid username or password", "status": 401},
}
