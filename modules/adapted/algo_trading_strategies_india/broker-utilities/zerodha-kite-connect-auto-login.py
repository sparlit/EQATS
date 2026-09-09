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


#!/usr/bin/env python3
"""
Kite Connect Auto-Login Script
Created by: Subash Krishnan

Contact Information:
- Phone/WhatsApp: +919605006699, +65-94675969
- Email: Available on LinkedIn

Social Links:
- LinkedIn: https://www.linkedin.com/in/buzzsubash
- Twitter: https://x.com/buzzsubash
- GitHub: https://github.com/buzzsubash
- Facebook: https://www.facebook.com/buzzsubash/
- Reddit: https://www.reddit.com/user/buzzsubash/
- Blog: https://emcsaninfo.wordpress.com/
- Credly: https://www.credly.com/users/subash-krishnan

Description: Automated login script for Zerodha Kite Connect API with 2FA support
Version: 1.1
Last Updated: July 2025
"""

import logging
import os
import threading
import time

import pyotp
import requests
from flask import Flask
from kiteconnect import KiteConnect
from werkzeug.serving import make_server

# ================================================================================================
# USER CONFIGURATION SECTION - MODIFY THESE VALUES AS NEEDED
# ================================================================================================

# Server Configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000

# Zerodha Kite Connect Credentials (REQUIRED - Update with your credentials)
USER_ID = "YOUR_USER_ID"  # Your Zerodha User ID
PASSWORD = "YOUR_PASSWORD"  # Your Zerodha Password
TOTP_KEY = "YOUR_TOTP_SECRET_KEY"  # Your TOTP Secret Key from Zerodha
API_KEY = "YOUR_API_KEY"  # Your Kite Connect API Key
API_SECRET = "YOUR_API_SECRET"  # Your Kite Connect API Secret

# Telegram Notification Settings (REQUIRED - Update with your bot details)
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # Your Telegram Bot Token
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"  # Your Telegram Chat ID for notifications

# File Path for Access Token Storage (OPTIONAL - Modify path as needed)
ACCESS_TOKEN_PATH = "/path/to/your/access_token.txt"  # Update with your preferred path

# Retry Configuration (OPTIONAL - Modify retry behavior)
MAX_LOGIN_RETRIES = 3  # Maximum number of login attempts
RETRY_DELAY_SECONDS = 5  # Delay between retry attempts

# Logging Configuration (OPTIONAL - Modify logging behavior)
LOG_LEVEL = logging.DEBUG  # Set to logging.INFO for less verbose output
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"  # Log message format

# ================================================================================================
# END OF USER CONFIGURATION SECTION
# ================================================================================================

# Configure logging
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)


class KiteAutoLoginConfig:
    """Configuration class for Kite Auto-Login"""

    # Server configuration
    PORT = SERVER_PORT
    HOST = SERVER_HOST

    # Zerodha credentials
    USER_ID = USER_ID
    PASSWORD = PASSWORD
    TOTP_KEY = TOTP_KEY
    API_KEY = API_KEY
    API_SECRET = API_SECRET

    # Telegram configuration
    TELEGRAM_TOKEN = TELEGRAM_BOT_TOKEN
    CHAT_ID_ERROR = TELEGRAM_CHAT_ID

    # File path for access token
    ACCESS_TOKEN_PATH = ACCESS_TOKEN_PATH

    # Retry configuration
    MAX_RETRIES = MAX_LOGIN_RETRIES
    RETRY_DELAY = RETRY_DELAY_SECONDS

    # API URLs (These rarely change)
    LOGIN_URL = "https://kite.zerodha.com/api/login"
    TWOFA_URL = "https://kite.zerodha.com/api/twofa"
    CONNECT_URL = "https://kite.trade/connect/login?api_key="


class ServerThread(threading.Thread):
    """Thread class to run Flask server in background"""

    def __init__(self, app, host, port):
        threading.Thread.__init__(self)
        self.server = make_server(host, port, app)
        self.ctx = app.app_context()
        self.ctx.push()
        self.host = host
        self.port = port

    def run(self):
        """Start the Flask server"""
        logging.info(f"Starting server on {self.host}:{self.port}")
        self.server.serve_forever()

    def shutdown(self):
        """Shutdown the Flask server"""
        logging.info("Shutting down server")
        self.server.shutdown()


class TelegramNotifier:
    """Class to handle Telegram notifications"""

    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send_message(self, text, chat_id):
        """Send message to Telegram chat"""
        try:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            response = requests.post(self.base_url, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            logging.exception(f"Failed to send Telegram message: {e}")
            return None


class KiteAutoLogin:
    """Main class for Kite Connect auto-login functionality"""

    def __init__(self):
        self.config = KiteAutoLoginConfig()
        self.telegram = TelegramNotifier(self.config.TELEGRAM_TOKEN)
        self.server = None
        self.app = Flask(__name__)

    def start_server(self):
        """Start the Flask server in a separate thread"""
        try:
            self.server = ServerThread(self.app, self.config.HOST, self.config.PORT)
            self.server.start()
            logging.info("Server started successfully")
        except Exception as e:
            logging.exception(f"Failed to start server: {e}")
            raise

    def stop_server(self):
        """Stop the Flask server"""
        if self.server:
            self.server.shutdown()
            logging.info("Server stopped")

    def save_access_token(self, access_token):
        """Save access token to specified file path"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config.ACCESS_TOKEN_PATH), exist_ok=True)

            # Save access token to file
            with open(self.config.ACCESS_TOKEN_PATH, "w") as token_file:
                token_file.write(access_token)

            logging.info(f"Access token saved successfully to: {self.config.ACCESS_TOKEN_PATH}")

        except Exception as e:
            logging.exception(f"Failed to save access token: {e}")
            raise

    def generate_totp(self):
        """Generate TOTP for 2FA authentication"""
        try:
            totp = pyotp.TOTP(self.config.TOTP_KEY)
            return totp.now()
        except Exception as e:
            logging.exception(f"Failed to generate TOTP: {e}")
            raise

    def perform_login(self):
        """Perform the complete login process"""
        try:
            # Create session for login
            req_session = requests.Session()
            req_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

            # Step 1: Login with credentials
            logging.info("Performing initial login...")
            login_response = req_session.post(
                self.config.LOGIN_URL,
                data={
                    "user_id": self.config.USER_ID,
                    "password": self.config.PASSWORD,
                },
                timeout=30,
            )

            if login_response.status_code != 200:
                msg = f"Login failed with status code: {login_response.status_code}"
                raise Exception(msg)

            login_data = login_response.json()
            request_id = login_data["data"]["request_id"]
            logging.info(f"Login successful, request_id: {request_id}")

            # Step 2: Two-factor authentication
            logging.info("Performing 2FA authentication...")
            twofa_code = self.generate_totp()

            twofa_response = req_session.post(
                self.config.TWOFA_URL,
                data={"user_id": self.config.USER_ID, "request_id": request_id, "twofa_value": twofa_code},
                timeout=30,
            )

            if twofa_response.status_code != 200:
                msg = f"2FA failed with status code: {twofa_response.status_code}"
                raise Exception(msg)

            logging.info("2FA authentication successful")

            # Step 3: Get request token
            logging.info("Getting request token...")
            api_session = req_session.get(f"{self.config.CONNECT_URL}{self.config.API_KEY}", timeout=30)

            # Extract request token from URL
            if "request_token=" not in api_session.url:
                msg = "Request token not found in response URL"
                raise Exception(msg)

            request_token = api_session.url.split("request_token=")[1].split("&")[0]
            logging.info(f"Request token obtained: {request_token}")

            # Step 4: Generate access token
            logging.info("Generating access token...")
            kite = KiteConnect(api_key=self.config.API_KEY)
            session_data = kite.generate_session(request_token, api_secret=self.config.API_SECRET)

            access_token = session_data["access_token"]
            logging.info(f"Access token generated: {access_token}")

            # Save access token to file
            self.save_access_token(access_token)

            # Send success notification
            success_message = f"✅ Access token successfully generated: {access_token}"
            self.telegram.send_message(success_message, self.config.CHAT_ID_ERROR)

            return request_token, access_token, kite

        except Exception as e:
            error_message = f"❌ Desktop Connect Program Error: {e!s}"
            logging.exception(error_message)
            self.telegram.send_message(error_message, self.config.CHAT_ID_ERROR)
            raise

    def autologin_with_retry(self, max_retries=None, retry_delay=None):
        """Perform auto-login with retry mechanism"""
        max_retries = max_retries or self.config.MAX_RETRIES
        retry_delay = retry_delay or self.config.RETRY_DELAY

        for attempt in range(max_retries):
            try:
                logging.info(f"Login attempt {attempt + 1}/{max_retries}")
                return self.perform_login()

            except Exception as e:
                logging.exception(f"Login attempt {attempt + 1} failed: {e}")

                if attempt < max_retries - 1:
                    logging.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logging.exception("All login attempts failed")
                    raise
        return None

    def run(self):
        """Main method to run the auto-login process"""
        try:
            # Start the server
            logging.info(f"Starting Kite Auto-Login Server on http://{self.config.HOST}:{self.config.PORT}")
            self.start_server()

            # Perform auto-login
            request_token, access_token, kite = self.autologin_with_retry()

            # Display results
            print(f"\n{'=' * 50}")
            print("✅ LOGIN SUCCESSFUL")
            print(f"{'=' * 50}")
            print(f"Access Token: {access_token}")
            print(f"Request Token: {request_token}")
            print(f"{'=' * 50}")

            # Get and display user profile
            try:
                profile = kite.profile()
                print(f"User Profile: {profile}")
            except Exception as e:
                logging.warning(f"Failed to get user profile: {e}")

        except Exception as e:
            error_message = f"❌ Desktop Connect Program Critical Error: {e!s}"
            logging.exception(error_message)
            self.telegram.send_message(error_message, self.config.CHAT_ID_ERROR)
            print(f"Error: {e}")

        finally:
            # Always stop the server
            self.stop_server()


def main():
    """Main function to run the application"""
    try:
        kite_login = KiteAutoLogin()
        kite_login.run()
    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
    except Exception as e:
        logging.exception(f"Application failed: {e}")


if __name__ == "__main__":
    main()
