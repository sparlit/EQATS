import configparser
import datetime
import json
from typing import Dict, List, Optional, Union

import pytz
import requests
from bs4 import BeautifulSoup


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
    return round(round(price / tick_size) * tick_size, 2)


class CorporateDisclosure:
    def __init__(self):
        self.config = self.read_config("nseurl.conf")
        self.url = self.config.get("nseapi", "url")
        self.output_data = "./docs/coy_disclosures.json"
        self.data = self.fetch_data()

    @staticmethod
    def read_config(file_path: str) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(file_path)
        return parser

    def fetch_data(self) -> list[dict[str, str]]:
        try:
            res = requests.get(self.url)
            res.raise_for_status()
        except requests.RequestException as e:
            print(f"Failed to fetch data: {e}")
            return []

        soup = BeautifulSoup(res.text, "xml")
        entries = soup.find_all("entry")
        print(f"{len(entries)}, rows of data received")

        result = []
        for entry in entries:

            def get_text(tag: str) -> str:
                elem = entry.find(tag)
                return elem.get_text() if elem is not None else ""

            result.append(
                {
                    "updated": get_text("updated"),
                    "headline": get_text("Description"),
                    "location": get_text("Url"),
                    "news_class": get_text("Type_of_Submission"),
                    "company_name": get_text("CompanyName"),
                    "company_symbol": get_text("CompanySymbol"),
                    "date_modified": get_text("Modified"),
                    "date_created": get_text("Created"),
                }
            )
        return result

    def to_json(self) -> None:
        try:
            with open(self.output_data, "w") as f:
                json.dump(self.data, f, indent=4)
        except Exception as err:
            print(f"Failed to save to JSON: {err}")

    def save_filtered_data(self, key: str, value: str, file_name: str) -> None:
        filtered = [item for item in self.data if item.get(key) == value]
        try:
            with open(file_name, "w") as f:
                json.dump(filtered, f, indent=4)
        except Exception as err:
            print(f"Failed to save filtered data: {err}")
