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


from os import getenv

from dotenv import load_dotenv
from flask import Flask, redirect, url_for
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_restful import Api
from resources.errors import errors
from resources.routes import initialize_routes

from database.models import initialize_db

load_dotenv()
app = Flask(__name__, static_folder="../build", static_url_path="/")
app.config["JWT_SECRET_KEY"] = getenv("JWT_SECRET_KEY")

api = Api(app, errors=errors)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

app.config["MONGODB_SETTINGS"] = {"host": "mongodb://localhost/stock_exchange"}


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for("index"))


initialize_db(app)
initialize_routes(api)

if __name__ == "__main__":
    app.run(port=57597)
