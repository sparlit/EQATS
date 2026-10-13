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


import os

from flask import Flask, redirect, request
from upstox_api.api import *

app = Flask(__name__)


@app.route("/")
def demo():
    """Redirects user to login page"""
    s = Session(os.getenv("UPSTOX_API_KEY"))
    s.set_redirect_uri(os.getenv("UPSTOX_REDIRECT_URI"))
    s.set_api_secret(os.getenv("UPSTOX_API_SECRET"))
    url = s.get_login_url()
    return redirect(url)


@app.route("/callback", methods=["GET"])
def callback():
    """Receives the callback from server and gets the access token."""
    temp_server_shutdown_url = "http://127.0.0.1:5000/shutdown"
    code = request.args["code"]
    s = Session(os.getenv("UPSTOX_API_KEY"))
    s.set_redirect_uri(os.getenv("UPSTOX_REDIRECT_URI"))
    s.set_api_secret(os.getenv("UPSTOX_API_SECRET"))
    s.set_code(code)
    access_token = s.retrieve_access_token()
    html_code = f"""
        Access token : {access_token}
        <br>
        <b>Go back to the terminal now!</b>
        <script>
            setInterval(function() {{window.location="{temp_server_shutdown_url}"}}, 2000);
        </script>
        """
    app.queue.put(access_token)
    return html_code


@app.route("/shutdown")
def shutdown():
    """Shuts down flask server."""
    func = request.environ.get("werkzeug.server.shutdown")
    if func is None:
        raise RuntimeError("Not running with Werkzeug Server")
    func()
    return "Server Shutting down..."
