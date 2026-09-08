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


import json
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Dict

import requests
from mthrottle import Throttle

throttleConfig = {
    "default": {
        "rps": 3,
    },
}

th = Throttle(throttleConfig, 10)


class RequestTransport:
    def __init__(self, folder: Path, headers: dict[str, Any], timeout: int = 15) -> None:
        self.timeout = timeout
        self.folder = folder

        self._session = requests.Session()
        self.cookie_path = folder / "nse_cookies_requests.json"

        self._session.headers.update(headers)
        self._session.cookies.update(self._getCookies())

    def _setCookies(self):
        r = self.request("https://www.nseindia.com/option-chain")

        cookies = r.cookies
        self.cookie_path.write_text(json.dumps(requests.utils.dict_from_cookiejar(cookies)))

        return cookies

    def _getCookies(self):
        if self.cookie_path.exists():
            cookies = requests.utils.add_dict_to_cookiejar(CookieJar(), json.loads(self.cookie_path.read_bytes()))

            if self._hasCookiesExpired(cookies):
                cookies = self._setCookies()

            return cookies

        return self._setCookies()

    @staticmethod
    def _hasCookiesExpired(cookies) -> bool:
        return any(cookie.is_expired() for cookie in cookies)

    def exit(self):
        self._session.close()
        self.cookie_path.unlink(missing_ok=True)

    def download(self, url: str, folder: Path):
        """Download a large file in chunks from the given url.
        Returns pathlib.Path object of the downloaded file
        """
        fname = folder / url.rsplit("/", maxsplit=1)[-1]

        th.check()

        with self._session.get(url, stream=True, timeout=self.timeout) as r:
            contentType = r.headers.get("content-type")

            if contentType and "text/html" in contentType:
                msg = "NSE file is unavailable or not yet updated."
                raise RuntimeError(msg)

            with fname.open(mode="wb") as f:
                for chunk in r.iter_content(chunk_size=1000000):
                    f.write(chunk)

        return fname

    def request(self, url, params=None):
        """Make a http request"""
        th.check()

        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
        except requests.ReadTimeout as e:
            msg = "Request timed out"
            raise TimeoutError(msg) from e
        except requests.exceptions.ConnectionError as e:
            self.exit()
            msg = "The connection to the remote server was unexpectedly closed."
            raise ConnectionError(msg) from e

        if not 200 <= r.status_code < 300:
            msg = f"{url} {r.status_code}: {r.reason}"
            raise ConnectionError(msg)

        return r
