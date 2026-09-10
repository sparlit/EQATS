import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    elif dt.tzinfo is None:
        now = ist.localize(dt)
    else:
        now = dt.astimezone(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(price / tick_size) * tick_size


try:
    from django.contrib import admin
    from django.urls import path
    from visitors.service import views

    urlpatterns = [
        path("admin/", admin.site.urls),
        path("visitors/", views.VisitorAPI.as_view()),
    ]
except ImportError:
    urlpatterns = []
