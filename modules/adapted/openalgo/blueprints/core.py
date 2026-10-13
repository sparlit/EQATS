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


import base64
import io

import qrcode
from blueprints.apikey import generate_api_key
from database.auth_db import upsert_api_key
from database.user_db import add_user, find_user_by_username
from flask import Blueprint, flash, redirect, request, session, url_for
from utils.logging import get_logger

logger = get_logger(__name__)

core_bp = Blueprint("core_bp", __name__)


# Note: GET /setup is served by react_bp (React frontend)
# This route only handles POST for form submission from React
@core_bp.route("/setup", methods=["POST"])
def setup():
    if find_user_by_username() is not None:
        return redirect(url_for("auth.login"))

    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]

    # Validate password strength
    from utils.auth_utils import validate_password_strength

    is_valid, error_message = validate_password_strength(password)
    if not is_valid:
        flash(error_message, "error")
        return redirect(url_for("react.react_setup"))

    # Add the new admin user
    user = add_user(username, email, password, is_admin=True)
    if user:
        logger.info(f"New admin user {username} created successfully")

        # Automatically generate and save API key
        api_key = generate_api_key()
        key_id = upsert_api_key(username, api_key)
        if not key_id:
            logger.error(f"Failed to create API key for user {username}")
        else:
            logger.info(f"API key created successfully for user {username}")

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(user.get_totp_uri())
        qr.make(fit=True)

        # Create QR code image
        img_buffer = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(img_buffer, format="PNG")
        qr_code = base64.b64encode(img_buffer.getvalue()).decode()

        # Store TOTP setup in session temporarily for later access if needed.
        # NB: deliberately not storing the TOTP secret in the Flask session.
        # The default session cookie is signed but NOT encrypted; placing the
        # secret there leaks it to anyone who reads the cookie value (browser
        # extension, HAR export, support-ticket attachment, etc.). The QR
        # code rendered above is sufficient for the user to enrol their
        # authenticator app; the secret then lives only in the encrypted
        # users.totp_secret column.
        session["totp_setup"] = True
        session["username"] = username
        session["qr_code"] = qr_code

        # Flash message with SMTP setup info and redirect to login
        flash(
            "Account created successfully! Please configure your SMTP credentials in Profile settings for password recovery.",
            "success",
        )
        return redirect(url_for("auth.login"))
    else:
        # If the user already exists or an error occurred, show an error message
        logger.error(f"Failed to create admin user {username}")
        flash("User already exists or an error occurred", "error")
        return redirect(url_for("react.react_setup"))
