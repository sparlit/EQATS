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


# useful for handling different item types with a single interface
import logging

import pymongo
from scrapy.exceptions import DropItem

logger = logging.getLogger(__name__)


class NseScraperPipeline:
    collection = "stock_data"

    def __init__(self, mongodb_uri, mongo_db):
        self.db = None
        self.client = None
        self.mongodb_uri = mongodb_uri
        self.mongo_db = mongo_db
        if not self.mongodb_uri:
            raise ValueError("MongoDB URI not set")
        if not self.mongo_db:
            raise ValueError("Mongo DB not set")

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            mongodb_uri=crawler.settings.get("MONGODB_URI"),
            mongo_db=crawler.settings.get("MONGO_DATABASE", "nse_data"),
        )

    def open_spider(self, spider):
        """Called when spider is opened"""
        self.client = pymongo.MongoClient(self.mongodb_uri)
        self.db = self.client[self.mongo_db]

        # Create unique index on ticker_symbol to prevent duplicates
        try:
            self.db[self.collection].create_index(
                [("ticker_symbol", pymongo.ASCENDING)], unique=True
            )
            logger.info(f"Created unique index on {self.collection}.ticker_symbol")
        except pymongo.errors.OperationFailure as e:
            logger.warning(f"Index creation warning: {e}")

    def close_spider(self, spider):
        """Called when spider is closed"""
        self.client.close()
        logger.info("MongoDB connection closed")

    def process_item(self, item, spider):
        """Process item and store to database"""
        try:
            # Validate required fields
            if not item.get("ticker_symbol"):
                raise DropItem(f"Missing ticker_symbol in {item}")
            if not item.get("stock_name"):
                raise DropItem(f"Missing stock_name in {item}")
            if item.get("stock_price") is None:
                raise DropItem(f"Missing stock_price in {item}")

            # Convert to dict
            data = dict(item)

            # Replace or insert the document
            result = self.db[self.collection].replace_one(
                {"ticker_symbol": data["ticker_symbol"]}, data, upsert=True
            )

            if result.matched_count:
                logger.debug(f"Updated stock data for {data['ticker_symbol']}")
            else:
                logger.debug(f"Inserted stock data for {data['ticker_symbol']}")

            return item

        except DropItem as e:
            logger.warning(f"Dropped item: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            raise DropItem(f"Failed to process item: {e}")
