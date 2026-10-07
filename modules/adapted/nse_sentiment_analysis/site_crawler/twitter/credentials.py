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


import xml.etree.ElementTree as ET

import tweepy


class Credentials:
    def __init__(self):
        self.credential_xml = "twitter-credentials.xml"

    def get_twitter_credentials(self):
        credential_xml_data = ET.parse(self.credential_xml).getroot()

        return (
            credential_xml_data[0].text,
            credential_xml_data[1].text,
            credential_xml_data[2].text,
            credential_xml_data[3].text,
        )

    def authentinticate_twitter(self):
        twitter_credentials = self.get_twitter_credentials()
        auth = tweepy.OAuthHandler(twitter_credentials[0], twitter_credentials[1])
        auth.set_access_token(twitter_credentials[2], twitter_credentials[3])
        api = tweepy.API(auth)
        return api
