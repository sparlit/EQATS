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


import argparse
import contextlib
import logging
import os
import threading
from datetime import datetime

import psycopg2
import pyotp
import requests
import yaml
from flask import Flask
from kiteconnect import KiteConnect
from werkzeug.serving import make_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

PORT = 5000
HOST = "127.0.0.1"

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "clients_config.yaml")


def load_account_config(account_name):
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    master = config["master_account"]
    if master["name"] == account_name:
        return config, master

    for client in config.get("clients", []):
        if client["name"] == account_name:
            return config, client

    msg = f"Account '{account_name}' not found in clients_config.yaml"
    raise ValueError(msg)


class ServerThread(threading.Thread):
    def __init__(self, app):
        threading.Thread.__init__(self)
        self.server = make_server(HOST, PORT, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def autologin(config, account):
    db = config["database"]
    tg = config.get("telegram", {})
    telegram_token = tg.get("token", "")
    chat_id = tg.get("error_chat_id", "")

    conn_params = {
        "host": db["host"],
        "port": db["port"],
        "dbname": db["name"],
        "user": db["user"],
        "password": db["password"],
    }

    def notify(text):
        if not telegram_token or not chat_id:
            return
        with contextlib.suppress(Exception):
            requests.post(
                f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=5,
            )

    def save_token_to_db(access_token, request_token):
        sql = """
            INSERT INTO master_accounts (name, user_id, api_key, api_secret, totp_key, password,
                                         access_token, request_token, token_generated_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                access_token       = EXCLUDED.access_token,
                request_token      = EXCLUDED.request_token,
                token_generated_at = EXCLUDED.token_generated_at,
                updated_at         = EXCLUDED.updated_at
        """
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute(
            sql,
            (
                account["name"],
                account["user_id"],
                account["api_key"],
                account["api_secret"],
                account["totp_key"],
                account["password"],
                access_token,
                request_token,
                now,
                now,
            ),
        )
        conn.commit()
        cursor.close()
        conn.close()

    while True:
        try:
            session = requests.Session()
            twofa = pyotp.TOTP(account["totp_key"]).now()
            login_resp = session.post(
                "https://kite.zerodha.com/api/login",
                data={"user_id": account["user_id"], "password": account["password"]},
            ).json()
            request_id = login_resp["data"]["request_id"]
            session.post(
                "https://kite.zerodha.com/api/twofa",
                data={"user_id": account["user_id"], "request_id": request_id, "twofa_value": twofa},
            )
            api_session = session.get(f"https://kite.trade/connect/login?api_key={account['api_key']}")
            request_token = api_session.url.split("request_token=")[1].split("&")[0]

            kite = KiteConnect(api_key=account["api_key"])
            data = kite.generate_session(request_token, api_secret=account["api_secret"])
            access_token = data["access_token"]

            token_file = account["access_token_file"]
            os.makedirs(os.path.dirname(os.path.abspath(token_file)), exist_ok=True)
            with open(token_file, "w") as f:
                f.write(access_token)

            save_token_to_db(access_token, request_token)
            notify(f"✅ {account['name']}: Access token generated")
            logging.info(f"Login successful for {account['name']}")
            return request_token, access_token, kite

        except Exception as e:
            logging.exception(f"Login error for {account['name']}: {e}")
            notify(f"❌ {account['name']} login error: {e}")
            continue


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kite single account login")
    parser.add_argument("--account", required=True, help="Account name as defined in clients_config.yaml")
    args = parser.parse_args()

    config, account = load_account_config(args.account)

    app = Flask(__name__)
    server = ServerThread(app)
    server.start()

    try:
        request_token, access_token, kite = autologin(config, account)
        print(f"Access token: {access_token}")
        print(f"Profile: {kite.profile()}")
    except Exception as e:
        logging.exception(f"Error: {e}")
    finally:
        server.shutdown()
