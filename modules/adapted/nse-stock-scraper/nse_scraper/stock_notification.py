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


import logging
import os

import africastalking as at
import pymongo
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

at_username = os.getenv("at_username")
at_api_key = os.getenv("at_api_key")
mobile_number = os.getenv("mobile_number")
mongo_uri = os.getenv("MONGODB_URI")

# Initialize the Africa's Talking SDK
at.initialize(at_username, at_api_key)
sms = at.SMS
account = at.Application


def stock_notification(message: str, number: str):
    """Send an SMS notification with stock price data"""
    try:
        response = sms.send(message, [number])
        logger.info(f"SMS sent successfully: {response}")
        print(account.fetch_application_data())
    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")


def stock_query():
    """Query MongoDB for stock price and send notification if price meets threshold"""
    try:
        client = pymongo.MongoClient(mongo_uri)
        db = client["nse_data"]
        collection = db["stock_data"]

        # Find latest stock data for BAT
        ticker_data = collection.find_one({"ticker_symbol": "BAT"}, sort=[("created_at", -1)])

        if not ticker_data:
            logger.warning("No data found for ticker BAT")
            return None

        stock_name = ticker_data.get("stock_name")
        stock_price = ticker_data.get("stock_price")

        if not stock_name or stock_price is None:
            logger.warning(f"Incomplete data for BAT: {ticker_data}")
            return None

        sms_data = {"stock_name": stock_name, "stock_price": stock_price}
        logger.info(f"Retrieved stock data: {sms_data}")

        message = f"Hello, the current stock price of {stock_name} is {stock_price}"

        # Send notification if price is >= 38
        if float(stock_price) >= 38:
            logger.info(f"Price threshold met ({stock_price} >= 38), sending notification")
            stock_notification(message, mobile_number)
            return sms_data
        else:
            logger.info(f"Price below threshold ({stock_price} < 38), no notification sent")
            return sms_data

    except Exception as e:
        logger.error(f"Error in stock_query: {e}", exc_info=True)
        return None
    finally:
        client.close()


if __name__ == "__main__":
    # Only run when executed directly, not when imported
    stock_query()
