import datetime
import json
import logging
import os
import random
import re
import sys
import time
import urllib.parse

import pandas as pd
import pytz
import requests


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


headers = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.79 Safari/537.36",
    "Sec-Fetch-User": "?1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
}

curl_headers = (
    "-H 'Connection: keep-alive' "
    "-H 'Cache-Control: max-age=0' "
    "-H 'DNT: 1' "
    "-H 'Upgrade-Insecure-Requests: 1' "
    "-H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.79 Safari/537.36' "
    "-H 'Sec-Fetch-User: ?1' "
    "-H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9' "
    "-H 'Sec-Fetch-Site: none' "
    "-H 'Sec-Fetch-Mode: navigate'"
)

mode = "vpn"

if mode == "vpn":

    def nsefetch(payload: str):
        def encode(url: str) -> str:
            if "%26" in url or "%20" in url:
                return url
            return urllib.parse.quote(url, safe=":/?&=")

        def refresh_cookies():
            os.popen(f'curl -c cookies.txt "https://www.nseindia.com" {curl_headers}').read()
            os.popen(
                f'curl -b cookies.txt -c cookies.txt "https://www.nseindia.com/option-chain" {curl_headers}'
            ).read()

        if not os.path.exists("cookies.txt"):
            refresh_cookies()

        encoded_url = encode(payload)
        cmd = f'curl -b cookies.txt "{encoded_url}" {curl_headers}'
        raw = os.popen(cmd).read()

        try:
            return json.loads(raw)
        except ValueError:
            refresh_cookies()
            raw = os.popen(cmd).read()
            try:
                return json.loads(raw)
            except ValueError:
                return {}


if mode == "local":

    def nsefetch(payload):

        try:
            s = requests.Session()
            s.get("https://www.nseindia.com", headers=headers, timeout=10)
            s.get("https://www.nseindia.com/option-chain", headers=headers, timeout=10)
            output = s.get(payload, headers=headers, timeout=10).json()
        except ValueError:
            output = {}
        return output
