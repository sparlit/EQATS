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


from flask import Blueprint, render_template
from flask_login import current_user, login_required

from .api import bnfRequiredData, fnfRequiredData, nfRequiredData

views = Blueprint("views", __name__)


@views.route("/")
@login_required
def home():
    return render_template("home.html", user=current_user)


@views.route("/nifty")
@login_required
def nifty():
    return render_template(
        "nifty.html", user=current_user, data=nfRequiredData, length=len(nfRequiredData)
    )


@views.route("/finnifty")
@login_required
def finnifty():
    return render_template(
        "finnifty.html", user=current_user, data=fnfRequiredData, length=len(fnfRequiredData)
    )


@views.route("/banknifty")
@login_required
def banknifty():
    return render_template(
        "banknifty.html", user=current_user, data=bnfRequiredData, length=len(bnfRequiredData)
    )
