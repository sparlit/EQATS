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
from datetime import datetime

from scrapy import Spider

logger = logging.getLogger(__name__)


class AfxScraperSpider(Spider):
    name = "afx_scraper"
    allowed_domains = ["afx.kwayisi.org"]
    start_urls = ["https://afx.kwayisi.org/nse/"]
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    def parse(self, response):
        """Parse stock data from the response"""
        logger.info(f"Processing: {response.url}")

        try:
            rows = response.css("table tbody tr")

            for row in rows:
                try:
                    # Extract raw data using XPath
                    raw_ticker = row.xpath("td[1]//text()").getall()
                    raw_name = row.xpath("td[2]//text()").getall()
                    raw_price = row.xpath("td[4]//text()").getall()
                    raw_change = row.xpath("td[5]//text()").getall()

                    # Clean and process data
                    ticker_symbol = self._clean_text(raw_ticker)
                    stock_name = self._clean_text(raw_name)
                    stock_price = self._clean_price(raw_price)
                    stock_change = self._clean_price(raw_change)

                    # Validate data
                    if not ticker_symbol or not stock_name or stock_price is None:
                        logger.debug(f"Skipping incomplete row: {raw_ticker}")
                        continue

                    yield {
                        "ticker_symbol": ticker_symbol,
                        "stock_name": stock_name,
                        "stock_price": stock_price,
                        "stock_change": stock_change,
                        "created_at": datetime.utcnow(),
                    }

                except Exception as e:
                    logger.error(f"Error processing row: {e}", exc_info=True)
                    continue

        except Exception as e:
            logger.error(f"Error parsing page {response.url}: {e}", exc_info=True)

    @staticmethod
    def _clean_text(text_list):
        """Clean and extract text from list"""
        if not text_list:
            return None

        cleaned = " ".join(text_list).strip()
        return cleaned if cleaned else None

    @staticmethod
    def _clean_price(price_list):
        """Clean and convert price to float"""
        if not price_list:
            return None

        cleaned = " ".join(price_list).strip()

        try:
            # Remove any non-numeric characters except decimal point
            cleaned = "".join(c for c in cleaned if c.isdigit() or c == ".")
            return float(cleaned) if cleaned else None
        except (ValueError, AttributeError) as e:
            logger.debug(f"Could not parse price from '{cleaned}': {e}")
            return None
